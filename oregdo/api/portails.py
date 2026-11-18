"""Routes par acteur (contrat : docs/12) : connexion, suivi citoyen, terrain, pré-collecteur, brigade, mairie, administration.

Un seul serveur, une seule application web : chaque route vérifie le rôle du compte connecté (securite.exiger_roles).
Messages d'erreur en français ; jamais de 500 pour une entrée invalide.
"""
import re
from collections import Counter
from datetime import date, datetime, timedelta, timezone
from typing import Any, Optional

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi.responses import FileResponse, JSONResponse
from pydantic import BaseModel

from .. import comptes, securite
from ..config import charger_config
from ..securite import exiger_admin, exiger_roles, utilisateur_courant
from ..verification import audio as vocal, base, controles, doublons, score, synthetique

router = APIRouter(tags=["acteurs"])
VERSION = "1.0"
FICHIERS_DEMO = ("bons.csv", "mal_forme.csv", "sans_photo.geojson")
TYPES_INTERVENTION = ("sensibilisation", "sanction")
CODE_SUIVI = re.compile(r"^[A-Za-z0-9-]{4,40}$")


def _refuser(message: str, code: int = 422):
    raise HTTPException(code, message)


def _erreur_compte(e: comptes.ErreurCompte):
    if e.code == 401:
        raise HTTPException(401, str(e), headers={"WWW-Authenticate": "Bearer"})
    raise HTTPException(e.code, str(e))


def _date(valeur, nom="date") -> str:
    """AAAA-MM-JJ, pas dans le futur. Vide : aujourd'hui."""
    if valeur in (None, ""):
        return date.today().isoformat()
    try:
        d = date.fromisoformat(str(valeur))
    except ValueError:
        _refuser(f"Le champ « {nom} » doit être une date AAAA-MM-JJ.")
    if d > date.today():
        _refuser(f"Le champ « {nom} » ne peut pas être dans le futur.")
    return d.isoformat()


def _nombre(valeur, nom, minimum, maximum, entier=False, exclusif=False):
    try:
        v = float(valeur)
    except (TypeError, ValueError):
        _refuser(f"Le champ « {nom} » doit être un nombre.")
    if v != v or v in (float("inf"), float("-inf")):
        _refuser(f"Le champ « {nom} » doit être un nombre fini.")
    if (v <= minimum if exclusif else v < minimum) or v > maximum:
        borne = f"supérieur à {minimum} (maximum {maximum})" if exclusif else f"compris entre {minimum} et {maximum}"
        _refuser(f"Le champ « {nom} » doit être {borne}.")
    if entier and v != int(v):
        _refuser(f"Le champ « {nom} » doit être un nombre entier.")
    return int(v) if entier else v


class Connexion(BaseModel):
    identifiant: Optional[Any] = None
    mot_de_passe: Optional[Any] = None


class ChangementMotDePasse(BaseModel):
    ancien: Optional[Any] = None
    nouveau: Optional[Any] = None


# ------------------------------------------------------------------ 1. accueil et public
@router.get("/sante")
def sante():
    conn = base.ouvrir()
    try:
        n, synth = conn.execute("SELECT COUNT(*), COALESCE(SUM(synthetique),0) FROM signalement").fetchone()
        return {"ok": True, "base_vide": n == 0, "demo_chargee": synth > 0, "nb_signalements": n, "version": VERSION}
    finally:
        conn.close()


@router.get("/suivi/{code}")
def suivi(code: str):
    """Suivi anonyme par code : ne révèle ni position, ni enquêteur, ni motifs détaillés."""
    if not CODE_SUIVI.match(code):
        _refuser("Code de suivi invalide.", 404)
    conn = base.ouvrir()
    try:
        s = conn.execute("SELECT id, statut, recu_le, depotoir_id FROM signalement WHERE code_suivi=?", (code,)).fetchone()
        if s is None:
            raise HTTPException(404, "Aucun signalement ne correspond à ce code.")
        confirme = bool(s["depotoir_id"] and conn.execute("SELECT 1 FROM depotoir WHERE id=? AND statut='verifie'", (s["depotoir_id"],)).fetchone())
        message = {"verifie": "Votre signalement est vérifié : le lieu est enregistré comme dépotoir.",
                   "a_confirmer": "Un agent de la brigade doit vérifier ce lieu sur place.",
                   "rejete": "Ce signalement n'a pas pu être retenu (position ou informations inutilisables)."}[s["statut"]]
        # Historique lisible : jamais le nom de l'agent ni le motif interne.
        etapes = {"verifie": "Lieu vérifié et enregistré comme dépotoir", "a_confirmer": "En attente de la visite d'un agent",
                  "rejete": "Signalement non retenu"}
        historique = []
        for j in conn.execute("SELECT nouveau_statut, agent, date FROM journal WHERE signalement_id=? ORDER BY id", (s["id"],)):
            qui = "contrôles automatiques" if j["agent"] == "automatique" else "agent de la brigade"
            historique.append({"date": j["date"], "statut": j["nouveau_statut"], "texte": f"{etapes[j['nouveau_statut']]} ({qui})"})
        return {"code_suivi": code, "statut": s["statut"], "message": message, "recu_le": s["recu_le"], "tas_confirme": confirme, "historique": historique}
    finally:
        conn.close()


def comptes_avis(conn, cfg) -> dict:
    """{depotoir_id: {"present": n, "disparu": n}} en appareils DISTINCTS (« disparu » : fenêtre récente seulement)."""
    av = cfg.securite.avis_voisins
    depuis = (datetime.now(timezone.utc) - timedelta(days=av.jours_disparu)).isoformat(timespec="seconds")
    sortie = {}
    for r in conn.execute("SELECT depotoir_id, type, COUNT(DISTINCT appareil) n FROM avis WHERE type='present' OR date>=? GROUP BY depotoir_id, type", (depuis,)):
        sortie.setdefault(r["depotoir_id"], {"present": 0, "disparu": 0})[r["type"]] = r["n"]
    return sortie


OBJECTIF_DEFI_MENSUEL = 50     # [H] objectif collectif affiché aux citoyens : hypothèse de communication, à fixer avec la mairie
JOURS_DEFI = 30


@router.get("/public/defi")
def defi_collectif():
    """Défi collectif de la commune : dépotoirs vérifiés ces 30 derniers jours. Aucune donnée personnelle, aucun classement de personnes
    ni de quartiers (un classement pousse à tricher et exclut) ; les données de démonstration et les essais du jury ne comptent pas."""
    depuis = (datetime.now(timezone.utc) - timedelta(days=JOURS_DEFI)).isoformat(timespec="seconds")
    conn = base.ouvrir()
    try:
        n = conn.execute("""SELECT COUNT(DISTINCT COALESCE(depotoir_id, -id)) FROM signalement
                            WHERE statut='verifie' AND synthetique=0 AND essai=0 AND recu_le>=?""", (depuis,)).fetchone()[0]
        return {"jours": JOURS_DEFI, "verifies": n, "objectif": OBJECTIF_DEFI_MENSUEL, "atteint": n >= OBJECTIF_DEFI_MENSUEL}
    finally:
        conn.close()


@router.get("/public/depotoirs")
def depotoirs_publics():
    """Carte publique : dépotoirs vérifiés seulement, position arrondie (≈ 100 m), aucun identifiant interne (une référence
    opaque permet seulement de donner un avis sur place)."""
    conn = base.ouvrir()
    try:
        avis = comptes_avis(conn, charger_config())
        feats = []
        for f in doublons.lister_depotoirs(conn)["features"]:
            p, (lon, lat) = f["properties"], f["geometry"]["coordinates"]
            a = avis.get(p["id"], {})
            feats.append({"type": "Feature", "geometry": {"type": "Point", "coordinates": [round(lon, 3), round(lat, 3)]},
                          "properties": {"niveau_confiance": "eleve" if p["nb_enqueteurs"] >= 2 or p["confiance"] >= 85 else "moyen",
                                         "synthetique": p["synthetique"], "ref": securite.ref_depotoir(p["id"]),
                                         "confirmations": p["nb_enqueteurs"], "disparu": a.get("disparu", 0)}})
        return {"type": "FeatureCollection", "synthetique": any(f["properties"]["synthetique"] for f in feats), "features": feats}
    finally:
        conn.close()


class AvisEntree(BaseModel):
    type: Optional[Any] = None
    lat: Optional[Any] = None
    lon: Optional[Any] = None
    appareil: Optional[Any] = None


def _gps(valeur, nom, borne):
    try:
        v = float(valeur)
    except (TypeError, ValueError):
        _refuser(f"Votre position GPS est nécessaire ({nom} absente ou illisible) : activez la localisation de votre téléphone.")
    if v != v or abs(v) > borne:
        _refuser(f"Votre position GPS est incorrecte ({nom}).")
    return v


@router.post("/public/depotoirs/{ref}/avis", status_code=201)
def donner_avis(ref: str, corps: AvisEntree, request: Request):
    """Un voisin, SUR PLACE, confirme un tas (« moi aussi je le vois ») ou dit qu'il n'est plus là. Sans compte.
    - « present » devient un vrai signalement du pipeline (appareil distinct = corroboration), regroupé avec le dépotoir ;
    - « disparu » est seulement enregistré : rien n'est supprimé, à partir de N appareils distincts le dépotoir est « à revérifier »."""
    cfg = charger_config()
    av = cfg.securite.avis_voisins
    if corps.type not in ("present", "disparu"):
        _refuser("Type d'avis inconnu : « present » (je le vois) ou « disparu » (il n'est plus là).")
    appareil = str(corps.appareil or "").strip()
    if not appareil or len(appareil) > 200:
        _refuser("Identifiant d'appareil manquant : rechargez l'application.")
    lat, lon = _gps(corps.lat, "latitude", 90), _gps(corps.lon, "longitude", 180)
    lim = cfg.securite.limitation_signalements
    securite.limiter("avis-ip:" + securite.ip_client(request), lim.max_par_ip, lim.fenetre_secondes)
    securite.limiter("avis-appareil:" + appareil, lim.max_par_appareil, lim.fenetre_secondes)
    conn = base.ouvrir()
    try:
        depot = next((d for d in conn.execute("SELECT * FROM depotoir WHERE statut='verifie'") if securite.ref_depotoir(d["id"]) == ref), None)
        if depot is None:
            raise HTTPException(404, "Ce dépotoir n'existe plus ou n'est plus vérifié.")
        distance = controles.distance_m(lat, lon, depot["lat"], depot["lon"])
        if distance > av.rayon_presence_m:
            _refuser(f"Vous êtes à environ {round(distance)} m du tas : approchez-vous (moins de {av.rayon_presence_m} m) pour donner votre avis sur place.")
        maintenant = datetime.now(timezone.utc)
        depuis = (maintenant - timedelta(hours=av.delai_heures)).isoformat(timespec="seconds")
        if conn.execute("SELECT 1 FROM avis WHERE depotoir_id=? AND type=? AND appareil=? AND date>=?", (depot["id"], corps.type, appareil, depuis)).fetchone():
            raise HTTPException(409, f"Vous avez déjà donné cet avis sur ce tas (un avis par appareil et par {av.delai_heures} h).")
        sid = None
        if corps.type == "present":
            # La confirmation entre dans le pipeline comme un signalement de cet appareil, À LA POSITION du dépotoir (même tas).
            sig = {"lat": depot["lat"], "lon": depot["lon"], "appareil": appareil, "enqueteur": None, "secteur": None,
                   "horodatage": maintenant.isoformat(timespec="seconds"), "source": "soutien"}
            sid = score.verifier_et_enregistrer(conn, sig, [], controles.reference(), cfg, synthetique=bool(depot["synthetique"]))["id"]
            doublons.consolider(conn, cfg)
        conn.execute("INSERT INTO avis (depotoir_id, type, appareil, distance_m, date, signalement_id) VALUES (?,?,?,?,?,?)",
                     (depot["id"], corps.type, appareil, round(distance, 1), maintenant.isoformat(timespec="seconds"), sid))
        conn.commit()
        c = comptes_avis(conn, cfg).get(depot["id"], {})
        if corps.type == "present":
            return {"message": "Merci : votre confirmation est enregistrée. Plus il y a de voisins qui confirment, plus ce tas est sûr.", "disparu": c.get("disparu", 0)}
        revoir = c.get("disparu", 0) >= av.min_disparu
        return {"message": ("Merci : plusieurs personnes disent que ce tas n'est plus là ; la brigade va le revérifier." if revoir
                            else "Merci : votre avis est enregistré. Si une autre personne confirme, la brigade revérifiera ce tas."),
                "disparu": c.get("disparu", 0), "a_reverifier": revoir}
    finally:
        conn.close()


# ------------------------------------------------------------------ 2. authentification
@router.post("/auth/connexion")
def connexion(corps: Connexion, request: Request):
    securite.limiter("connexion:" + securite.ip_client(request), 30, 600)
    conn = base.ouvrir()
    try:
        return comptes.connecter(conn, corps.identifiant, corps.mot_de_passe)
    except comptes.ErreurCompte as e:
        if e.code == 423:
            attente = getattr(e, "reessayer_dans_s", 60)
            return JSONResponse({"detail": str(e), "reessayer_dans_s": attente}, status_code=423, headers={"Retry-After": str(attente)})
        _erreur_compte(e)
    finally:
        conn.close()


@router.get("/auth/moi")
def moi(u=Depends(utilisateur_courant)):
    return {k: u.get(k) for k in ("identifiant", "nom", "role", "zone", "point", "derniere_connexion")}


@router.post("/auth/deconnexion")
def deconnexion(u=Depends(utilisateur_courant)):
    conn = base.ouvrir()
    try:
        if u.get("jti"):
            conn.execute("UPDATE session SET revoque=1 WHERE jti=?", (u["jti"],))
            conn.commit()
        securite.auditer(conn, u, "deconnexion")
        return {"message": "Vous êtes déconnecté."}
    finally:
        conn.close()


@router.post("/auth/mot-de-passe")
def mot_de_passe(corps: ChangementMotDePasse, u=Depends(utilisateur_courant)):
    conn = base.ouvrir()
    try:
        comptes.changer_mot_de_passe(conn, u["identifiant"], str(corps.ancien or ""), corps.nouveau)
        return {"message": "Mot de passe modifié."}
    except comptes.ErreurCompte as e:
        _erreur_compte(e)
    finally:
        conn.close()


# ------------------------------------------------------------------ 4. pré-collecteur
@router.get("/precollecteur/profil")
def profil_precollecteur(u=Depends(exiger_roles("precollecteur"))):
    return {k: u.get(k) for k in ("identifiant", "nom", "zone", "point")}


@router.post("/precollecteur/collectes", status_code=201)
def saisir_collecte(corps: dict, u=Depends(exiger_roles("precollecteur"))):
    kg = _nombre(corps.get("kg"), "kg", 0, 5000, exclusif=True)
    menages = _nombre(corps.get("nb_menages", 0), "nb_menages", 0, 2000, entier=True)
    jour = _date(corps.get("date"))
    point = str(corps.get("point") or u.get("point") or "")[:80] or None
    cle = corps.get("cle_client")
    if cle is not None and (not isinstance(cle, str) or not CODE_SUIVI.match(cle)):
        _refuser("La clé d'envoi est invalide (4 à 40 lettres, chiffres ou tirets).")
    conn = base.ouvrir()
    try:
        if cle:                                           # renvoi après une coupure : on renvoie la collecte déjà enregistrée, sans la doubler
            deja = conn.execute("SELECT id, date, kg, nb_menages, point FROM collecte WHERE utilisateur=? AND cle_client=?", (u["identifiant"], cle)).fetchone()
            if deja:
                return {**dict(deja), "utilisateur": u["identifiant"], "deja_enregistree": True}
        cid = conn.execute("INSERT INTO collecte (date, kg, nb_menages, point, utilisateur, saisi_le, cle_client) VALUES (?,?,?,?,?,?,?)",
                           (jour, kg, menages, point, u["identifiant"], base.maintenant(), cle or None)).lastrowid
        conn.commit()
        return {"id": cid, "date": jour, "kg": kg, "nb_menages": menages, "point": point, "utilisateur": u["identifiant"]}
    finally:
        conn.close()


@router.get("/precollecteur/collectes")
def lister_collectes(du: Optional[str] = None, au: Optional[str] = None, u=Depends(exiger_roles("precollecteur"))):
    cond, args = ["utilisateur=?"], [u["identifiant"]]
    if du:
        cond.append("date>=?"); args.append(_date(du, "du"))
    if au:
        cond.append("date<=?"); args.append(_date(au, "au"))
    conn = base.ouvrir()
    try:
        lignes = [dict(r) for r in conn.execute(f"SELECT id, date, kg, nb_menages, point FROM collecte WHERE {' AND '.join(cond)} ORDER BY date DESC, id DESC", args)]
        return {"collectes": lignes, "totaux": {"kg": round(sum(c["kg"] for c in lignes), 1), "nb_menages": sum(c["nb_menages"] for c in lignes),
                                                "nb_collectes": len(lignes)}}
    finally:
        conn.close()


@router.get("/calibrage", dependencies=[Depends(exiger_roles("mairie"))])
def calibrage():
    """Étalonnage du modèle sur les collectes saisies sur le terrain : mesure l'écart, ne modifie jamais les paramètres."""
    from ..planning import etalonnage
    conn = base.ouvrir()
    try:
        return etalonnage.etalonner(conn)
    finally:
        conn.close()


@router.get("/precollecteur/tournee")
def tournee_precollecteur(u=Depends(exiger_roles("precollecteur"))):
    """Tournées du plan courant qui passent par le point de regroupement de rattachement."""
    from . import plan as api_plan                      # import tardif : le moteur de plan est lourd
    point, zone = u.get("point"), u.get("zone")
    plan = api_plan._etat.get("plan")
    if not point:
        return {"disponible": False, "point": None, "zone": zone, "tournee": None, "message": "Aucun point de regroupement ne vous est rattaché : contactez la mairie."}
    if plan is None:
        return {"disponible": False, "point": point, "zone": zone, "tournee": None, "message": "Aucun plan n'est encore calculé par la mairie."}
    feats = [f for f in plan["tournees"]["features"] if any(a["id"] == point for a in f["properties"]["arrets"])]
    if not feats:
        return {"disponible": False, "point": point, "zone": zone, "tournee": None, "message": "Aucun camion ne passe par votre point dans le plan actuel."}
    return {"disponible": True, "point": point, "zone": zone, "tournee": {"type": "FeatureCollection", "features": feats},
            "message": f"{len(feats)} passage(s) de camion prévu(s) à votre point de regroupement."}


# ------------------------------------------------------------------ 5. brigade Laabal
def _bareme(cfg, recidive=False):
    mini, maxi = cfg.simulation.brigade_laabal.amende_fcfa
    m = cfg.securite.sanctions.recidive_multiplicateur if recidive else 1
    return int(mini * m), int(maxi * m)


@router.get("/brigade/file")
def file_brigade(statut: str = Query("a_confirmer"), u=Depends(exiger_roles("brigade"))):
    if statut not in base.STATUTS:
        _refuser(f"Statut inconnu « {statut} » : choisir parmi {', '.join(base.STATUTS)}.", 400)
    conn = base.ouvrir()
    try:
        liste = base.lister_signalements(conn, statut)
        liste.sort(key=lambda s: -(s["score"] or 0))
        return {"nombre": len(liste), "signalements": liste}
    finally:
        conn.close()


@router.get("/brigade/depotoirs")
def depotoirs_brigade(u=Depends(exiger_roles("brigade"))):
    conn = base.ouvrir()
    try:
        interv = {}
        for r in conn.execute("SELECT depotoir_id, type, COUNT(*) n FROM intervention GROUP BY depotoir_id, type"):
            interv.setdefault(r["depotoir_id"], {"sensibilisation": 0, "sanction": 0})[r["type"]] = r["n"]
        cfg, sortie = charger_config(), []
        avis = comptes_avis(conn, cfg)
        for f in doublons.lister_depotoirs(conn)["features"]:
            p, (lon, lat) = f["properties"], f["geometry"]["coordinates"]
            i = interv.get(p["id"], {"sensibilisation": 0, "sanction": 0})
            a = avis.get(p["id"], {})
            sortie.append({"id": p["id"], "lat": lat, "lon": lon, "confiance": p["confiance"], "nb_enqueteurs": p["nb_enqueteurs"],
                           "interventions": i, "sanction_possible": i["sensibilisation"] > 0, "synthetique": p["synthetique"],
                           "avis_present": a.get("present", 0), "avis_disparu": a.get("disparu", 0),
                           "a_reverifier": a.get("disparu", 0) >= cfg.securite.avis_voisins.min_disparu})
        sortie.sort(key=lambda d: (not d["a_reverifier"], -d["confiance"]))      # les tas signalés disparus d'abord
        return {"depotoirs": sortie}
    finally:
        conn.close()


@router.get("/brigade/bareme", dependencies=[Depends(exiger_roles("brigade", "mairie"))])
def bareme():
    cfg = charger_config()
    mini, maxi = _bareme(cfg)
    return {"amende_min_fcfa": mini, "amende_max_fcfa": maxi, "recidive_multiplicateur": cfg.securite.sanctions.recidive_multiplicateur,
            "base_legale": cfg.securite.sanctions.base_legale}


@router.post("/brigade/interventions", status_code=201)
def creer_intervention(corps: dict, u=Depends(exiger_roles("brigade"))):
    """Sensibilisation d'abord, sanction ensuite. Une sanction exige un dépotoir vérifié, une sensibilisation préalable
    (sauf flagrant délit motivé), un numéro de procès-verbal et un montant dans le barème (doublé en cas de récidive)."""
    cfg = charger_config()
    typ = corps.get("type")
    if typ not in TYPES_INTERVENTION:
        _refuser(f"Type d'intervention inconnu : choisir parmi {', '.join(TYPES_INTERVENTION)}.")
    did = _nombre(corps.get("depotoir_id"), "depotoir_id", 1, 2**62, entier=True)
    jour = _date(corps.get("date"))
    texte_max = cfg.verification.limites.texte_max
    issue = str(corps.get("issue") or "")[:texte_max] or None
    flagrant = bool(corps.get("flagrant_delit"))
    motif_flagrant = str(corps.get("motif_flagrant") or "").strip()[:texte_max] or None
    conn = base.ouvrir()
    try:
        depot = conn.execute("SELECT * FROM depotoir WHERE id=?", (did,)).fetchone()
        if depot is None:
            raise HTTPException(404, f"Dépotoir {did} introuvable.")
        if depot["statut"] != "verifie":
            raise HTTPException(409, "Intervention refusée : ce dépotoir n'est pas vérifié. Faites d'abord confirmer le signalement.")
        numero_pv = montant = None
        recidive = 0
        if typ == "sanction":
            deja = {r["type"]: r["n"] for r in conn.execute("SELECT type, COUNT(*) n FROM intervention WHERE depotoir_id=? GROUP BY type", (did,))}
            if not deja.get("sensibilisation") and not (flagrant and motif_flagrant):
                raise HTTPException(409, "Sanction refusée : aucune sensibilisation n'est enregistrée pour ce dépotoir. "
                                         "Sensibilisez d'abord, ou déclarez un flagrant délit avec son motif.")
            numero_pv = str(corps.get("numero_pv") or "").strip()[:60]
            if not numero_pv:
                _refuser("Le numéro du procès-verbal est obligatoire pour une sanction.")
            recidive = 1 if deja.get("sanction") else 0
            mini, maxi = _bareme(cfg, bool(recidive))
            montant = mini if corps.get("montant_fcfa") in (None, "") else _nombre(corps["montant_fcfa"], "montant_fcfa", 0, 10**9, entier=True)
            if not mini <= montant <= maxi:
                _refuser(f"Montant hors barème : {mini} à {maxi} FCFA{' (récidive : montant doublé)' if recidive else ''} "
                         f"({cfg.securite.sanctions.base_legale}).")
        elif flagrant:
            motif_flagrant = None                        # sans objet pour une sensibilisation
        iid = conn.execute("INSERT INTO intervention (depotoir_id, type, date, agent, issue, numero_pv, montant_fcfa, recidive, flagrant_delit, motif_flagrant, synthetique) "
                           "VALUES (?,?,?,?,?,?,?,?,?,?,?)",
                           (did, typ, jour, u["identifiant"], issue, numero_pv, montant, recidive, int(flagrant and typ == "sanction"), motif_flagrant,
                            int(bool(depot["synthetique"])))).lastrowid
        conn.commit()
        securite.auditer(conn, u, "intervention_" + typ, did, {"numero_pv": numero_pv, "montant_fcfa": montant})
        return {"id": iid, "depotoir_id": did, "type": typ, "date": jour, "agent": u["identifiant"], "issue": issue, "numero_pv": numero_pv,
                "montant_fcfa": montant, "recidive": bool(recidive), "base_legale": cfg.securite.sanctions.base_legale}
    finally:
        conn.close()


@router.get("/brigade/interventions", dependencies=[Depends(exiger_roles("brigade", "mairie"))])
def lister_interventions(depotoir_id: Optional[int] = None):
    conn = base.ouvrir()
    try:
        sql, args = "SELECT * FROM intervention", []
        if depotoir_id is not None:
            sql, args = sql + " WHERE depotoir_id=?", [depotoir_id]
        return {"interventions": [dict(r) for r in conn.execute(sql + " ORDER BY id DESC", args)]}
    finally:
        conn.close()


@router.get("/brigade/audio/{sid}")
def ecouter_message_vocal(sid: int, u=Depends(exiger_roles("brigade"))):
    """Message vocal d'un signalement : brigade et administration seulement. Chaque écoute est inscrite au journal d'audit."""
    conn = base.ouvrir()
    try:
        trouve = vocal.chemin(conn, sid)
        if trouve is None:
            raise HTTPException(404, "Aucun message vocal pour ce signalement (absent, ou effacé après la durée de conservation).")
        securite.auditer(conn, u, "ecoute_message_vocal", sid)
        return FileResponse(trouve[0], media_type=trouve[1], headers={"Cache-Control": "private, no-store"})
    finally:
        conn.close()


# ------------------------------------------------------------------ 6. mairie
@router.get("/mairie/kpi", dependencies=[Depends(exiger_roles("mairie"))])
def kpi_mairie():
    conn = base.ouvrir()
    try:
        par_statut = {k: 0 for k in base.STATUTS} | base.compter_par_statut(conn)
        nb_synth = conn.execute("SELECT COUNT(*) FROM signalement WHERE synthetique=1 AND essai=0").fetchone()[0]
        iv = conn.execute("SELECT type, COUNT(*) n, COALESCE(SUM(montant_fcfa),0) m FROM intervention GROUP BY type").fetchall()
        issues = Counter(r["issue"] or "non précisée" for r in conn.execute("SELECT issue FROM intervention"))
        col = conn.execute("SELECT COALESCE(SUM(kg),0), COALESCE(SUM(nb_menages),0), COUNT(*) FROM collecte").fetchone()
        par_point = [dict(r) for r in conn.execute("SELECT COALESCE(point,'non précisé') point, ROUND(SUM(kg),1) kg, COUNT(*) nb_collectes FROM collecte GROUP BY point ORDER BY kg DESC")]
        return {"signalements": {"par_statut": par_statut, "total": sum(par_statut.values()), "synthetique": nb_synth > 0},
                "depotoirs_verifies": conn.execute("SELECT COUNT(*) FROM depotoir WHERE statut='verifie'").fetchone()[0],
                "interventions": {"sensibilisation": next((r["n"] for r in iv if r["type"] == "sensibilisation"), 0),
                                  "sanction": next((r["n"] for r in iv if r["type"] == "sanction"), 0),
                                  "montant_total_fcfa": sum(r["m"] for r in iv), "par_statut": dict(issues)},
                "collectes": {"kg": round(col[0], 1), "nb_menages": col[1], "nb_collectes": col[2], "par_point": par_point}}
    finally:
        conn.close()


# ------------------------------------------------------------------ 7. administration
class NouvelUtilisateur(BaseModel):
    identifiant: Optional[Any] = None
    nom: Optional[Any] = None
    role: Optional[Any] = None
    mot_de_passe: Optional[Any] = None
    zone: Optional[Any] = None
    point: Optional[Any] = None


@router.get("/admin/utilisateurs")
def liste_utilisateurs(u=Depends(exiger_admin)):
    conn = base.ouvrir()
    try:
        return {"utilisateurs": comptes.lister_utilisateurs(conn)}
    finally:
        conn.close()


@router.post("/admin/utilisateurs", status_code=201)
def creer_utilisateur(corps: NouvelUtilisateur, u=Depends(exiger_admin)):
    conn = base.ouvrir()
    try:
        nouveau = comptes.creer_utilisateur(conn, corps.identifiant, str(corps.nom or ""), corps.role, corps.mot_de_passe, corps.zone, corps.point)
        securite.auditer(conn, u, "compte_cree", nouveau["identifiant"], {"role": nouveau["role"]})
        return {"utilisateur": nouveau}
    except comptes.ErreurCompte as e:
        _erreur_compte(e)
    finally:
        conn.close()


@router.patch("/admin/utilisateurs/{identifiant}")
def modifier_utilisateur(identifiant: str, corps: dict, u=Depends(exiger_admin)):
    champs = {k: corps.get(k) for k in ("nom", "role", "zone", "point", "actif", "mot_de_passe") if k in corps}
    conn = base.ouvrir()
    try:
        if identifiant == u["identifiant"] and (champs.get("actif") is False or (champs.get("role") not in (None, "admin"))):
            _refuser("Vous ne pouvez pas désactiver votre propre compte ni retirer votre rôle d'administrateur.", 409)
        res = comptes.modifier_utilisateur(conn, identifiant, **champs)
        securite.auditer(conn, u, "compte_modifie", identifiant, {k: v for k, v in champs.items() if k != "mot_de_passe"})
        return {"utilisateur": res}
    except comptes.ErreurCompte as e:
        _erreur_compte(e)
    finally:
        conn.close()


@router.delete("/admin/utilisateurs/{identifiant}")
def desactiver_utilisateur(identifiant: str, u=Depends(exiger_admin)):
    if identifiant == u["identifiant"]:
        _refuser("Vous ne pouvez pas désactiver votre propre compte.", 409)
    conn = base.ouvrir()
    try:
        res = comptes.modifier_utilisateur(conn, identifiant, actif=False)
        securite.auditer(conn, u, "compte_desactive", identifiant)
        return {"utilisateur": res}
    except comptes.ErreurCompte as e:
        _erreur_compte(e)
    finally:
        conn.close()


@router.get("/admin/audit")
def journal_audit(limite: int = Query(100, ge=1, le=1000), utilisateur: Optional[str] = None, u=Depends(exiger_admin)):
    conn = base.ouvrir()
    try:
        sql, args = "SELECT id, date, utilisateur, role, action, cible, details FROM audit", []
        if utilisateur:
            sql, args = sql + " WHERE utilisateur=?", [utilisateur]
        return {"evenements": [dict(r) for r in conn.execute(sql + " ORDER BY id DESC LIMIT ?", args + [limite])]}
    finally:
        conn.close()


def _etat_base(conn) -> dict:
    n, synth, essais = conn.execute("SELECT COUNT(*), COALESCE(SUM(synthetique),0), COALESCE(SUM(essai),0) FROM signalement").fetchone()
    return {"nb_signalements": n, "nb_synthetiques": synth, "nb_essais": essais,
            "nb_utilisateurs": conn.execute("SELECT COUNT(*) FROM utilisateur").fetchone()[0],
            "base_vide": n == 0, "demo_chargee": synth > 0, "secret_source": securite.source_secret()}


@router.get("/admin/etat")
def etat_admin(u=Depends(exiger_admin)):
    conn = base.ouvrir()
    try:
        return _etat_base(conn)
    finally:
        conn.close()


@router.post("/admin/demo/charger")
def charger_demo(u=Depends(exiger_admin)):
    """Charge le jeu de démonstration (signalements piégés générés). Tout est marqué synthétique."""
    conn = base.ouvrir()
    try:
        if conn.execute("SELECT 1 FROM signalement WHERE synthetique=1 LIMIT 1").fetchone():
            raise HTTPException(409, "Une démonstration est déjà chargée : retirez-la d'abord.")
        bilan = synthetique.peupler(conn, charger_config())
        securite.auditer(conn, u, "demo_chargee", None, bilan)
        return {"message": f"Démonstration chargée : {bilan['signalements_application']} signalements synthétiques.", "bilan": bilan}
    finally:
        conn.close()


@router.post("/admin/demo/retirer")
def retirer_demo(u=Depends(exiger_admin)):
    """Retire UNIQUEMENT les lignes synthétiques (les vrais signalements ne sont jamais touchés)."""
    conn = base.ouvrir()
    try:
        ids = [r[0] for r in conn.execute("SELECT id FROM signalement WHERE synthetique=1")]
        marques = ",".join("?" * len(ids))
        retires = {"signalements": len(ids)}
        if ids:
            conn.execute(f"DELETE FROM journal WHERE signalement_id IN ({marques})", ids)
            conn.execute(f"DELETE FROM photo WHERE signalement_id IN ({marques})", ids)
            conn.execute(f"DELETE FROM signalement WHERE id IN ({marques})", ids)
        retires["interventions"] = conn.execute("DELETE FROM intervention WHERE synthetique=1").rowcount
        retires["lignes_refusees"] = conn.execute(f"DELETE FROM ligne_refusee WHERE fichier IN ({','.join('?' * len(FICHIERS_DEMO))})", FICHIERS_DEMO).rowcount
        retires["depotoirs"] = conn.execute("DELETE FROM depotoir WHERE synthetique=1 AND id NOT IN (SELECT depotoir_id FROM signalement WHERE depotoir_id IS NOT NULL) "
                                            "AND id NOT IN (SELECT depotoir_id FROM intervention)").rowcount
        conn.commit()
        doublons.consolider(conn, charger_config())
        securite.auditer(conn, u, "demo_retiree", None, retires)
        return {"message": "Démonstration retirée.", "retires": retires}
    finally:
        conn.close()
