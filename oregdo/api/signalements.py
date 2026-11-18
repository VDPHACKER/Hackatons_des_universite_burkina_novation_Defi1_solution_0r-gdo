"""Routeur FastAPI des signalements (monté sous /api par oregdo/app.py). Messages en français."""
from collections import Counter
from typing import Any, Optional

from fastapi import APIRouter, Depends, File, HTTPException, Query, Request, Response, UploadFile
from pydantic import BaseModel, Field, model_validator

from ..config import charger_config
from .. import securite
from ..securite import exiger_roles, utilisateur_optionnel
from ..verification import audio as vocal, base, controles, doublons, importation, lot, score
from ..verification.lot import booleen as _booleen, decoder_photo as _decoder_photo, nombre_fini as _nombre_ou_none, texte as _texte

router = APIRouter(tags=["signalements"])


class SignalementEntree(BaseModel):
    """Signalement envoyé par l'application. Tolérant : formes multiples acceptées, champs inconnus ignorés,
    valeurs absurdes acceptées puis rejetées (avec motif) par les contrôles."""
    lat: Optional[Any] = Field(None, description="Latitude (degrés décimaux)")
    lon: Optional[Any] = Field(None, description="Longitude (degrés décimaux)")
    secteur: Optional[Any] = None
    taille: Optional[Any] = None
    nature: Optional[Any] = Field(None, description="Chaîne ou liste (jointe par virgule)")
    caniveau: Optional[Any] = Field(None, description="true/false, 0/1, oui/non")
    accessibilite: Optional[Any] = None
    enqueteur: Optional[Any] = None
    appareil: Optional[Any] = None
    horodatage: Optional[Any] = Field(None, description="Date ISO 8601")
    precision_m: Optional[Any] = Field(None, description="Précision GPS annoncée par le téléphone, en mètres (au-delà du seuil : au mieux « à confirmer »)")
    cle_client: Optional[str] = Field(None, max_length=80, description="Clé tirée par le téléphone : un renvoi (coupure réseau) renvoie le même résultat, sans doublon")
    photos: list[Any] = Field(default_factory=list, description="0 à 5 photos en base64 (ou {data|base64: ...})")
    audio: Optional[Any] = Field(None, description="Message vocal facultatif en base64 (WebM, Ogg ou MP4) : donnée personnelle, effacé après 30 jours")
    synthetique: bool = False

    @model_validator(mode="before")
    @classmethod
    def _alias(cls, d):
        if isinstance(d, dict):
            d = dict(d)
            d.setdefault("horodatage", d.get("date_client"))
            if d.get("horodatage") is None:
                d["horodatage"] = d.get("date_client")
            if d.get("accessibilite") is None and d.get("accessible") is not None:
                d["accessibilite"] = d["accessible"]
            if d.get("photos") is None:
                d["photos"] = []
        return d

    def en_signalement(self) -> dict:
        s = {k: _texte(getattr(self, k)) for k in ("secteur", "taille", "nature", "accessibilite", "enqueteur", "appareil", "horodatage")}
        s.update(lat=_nombre_ou_none(self.lat), lon=_nombre_ou_none(self.lon), caniveau=_booleen(self.caniveau), source="application",
                 precision_m=_nombre_ou_none(self.precision_m))
        return s


class Revalidation(BaseModel):
    statut: str
    motif: str
    agent: Optional[str] = None      # ignoré : l'agent est le compte connecté


def _base():
    return base.ouvrir()


def _refuser(message, code=422):
    raise HTTPException(code, message)


def valider_entree(entree: "SignalementEntree", cfg) -> tuple[dict, list[bytes]]:
    """Contrôle les limites d'une entrée et la convertit. 422 en français pour toute entrée inutilisable (jamais de 500)."""
    lim = cfg.verification.limites
    sig = entree.en_signalement()
    for champ in ("secteur", "taille", "nature", "accessibilite", "enqueteur", "appareil", "horodatage"):
        if sig[champ] is not None and len(sig[champ]) > lim.texte_max:
            _refuser(f"Le champ « {champ} » est trop long ({len(sig[champ])} caractères ; maximum {lim.texte_max}).")
    for nom, borne in (("lat", 90), ("lon", 180)):
        v = sig[nom]
        libelle = "La latitude" if nom == "lat" else "La longitude"
        if v is None:
            _refuser(f"{libelle} est absente ou illisible : un nombre fini est attendu (ex. 12.37).")
        if abs(v) > borne:
            _refuser(f"{libelle} {v} est hors de l'intervalle [-{borne} ; {borne}].")
    if len(entree.photos) > lim.photos_max:
        _refuser(f"Trop de photos ({len(entree.photos)}) : maximum {lim.photos_max}.")
    photos = []
    for i, p in enumerate(entree.photos, 1):
        brut = p.get("data") or p.get("base64") or p.get("contenu") or "" if isinstance(p, dict) else p
        if len(str(brut)) * 3 // 4 > lim.photo_octets_max:
            _refuser(f"La photo {i} est trop volumineuse : maximum {lim.photo_octets_max // 1000} Ko.")
        photos.append(_decoder_photo(p))
    return sig, photos


@router.post("/signalements", status_code=201)
def deposer(entree: SignalementEntree, request: Request, u=Depends(utilisateur_optionnel)):
    """Dépose un signalement. Sans compte (citoyen) : limitation de débit par appareil et par IP, réponse réduite avec un
    code de suivi. Avec un compte : réponse complète (score, motifs), l'enquêteur est le compte connecté."""
    cfg = charger_config()
    deja = _deja_recu(entree.cle_client, u)                 # envoi répété après une coupure : même réponse, aucun doublon
    if deja is not None:
        return deja
    if u is None:
        lim = cfg.securite.limitation_signalements
        securite.limiter("ip:" + securite.ip_client(request), lim.max_par_ip, lim.fenetre_secondes)
        if entree.appareil:
            securite.limiter("appareil:" + str(entree.appareil)[:200], lim.max_par_appareil, lim.fenetre_secondes)
    sig, photos = valider_entree(entree, cfg)
    try:
        message_vocal = vocal.decoder(entree.audio, cfg)
    except vocal.AudioInvalide as e:
        _refuser(str(e))
    if u is not None:
        sig["enqueteur"], sig["utilisateur"] = u["identifiant"], u["identifiant"]
        sig["secteur"] = sig["secteur"] or u.get("zone")
    conn = _base()
    try:
        r = score.verifier_et_enregistrer(conn, sig, photos, controles.reference(), cfg,
                                          synthetique=bool(entree.synthetique and u and u["role"] == "admin"),
                                          utilisateur=sig.get("utilisateur"))
        if entree.cle_client:
            conn.execute("UPDATE signalement SET cle_client=? WHERE id=?", (entree.cle_client, r["id"]))
            conn.commit()
        if message_vocal:
            vocal.enregistrer(conn, r["id"], *message_vocal)
        vocal.purger(conn, cfg)                          # efface les messages vocaux arrivés à échéance (jamais le signalement)
        doublons.consolider(conn, cfg)
        message = _message(r["statut"], r["score"]) if u else _message_citoyen(r["statut"], r["code_suivi"])
        if u is None:
            return {"code_suivi": r["code_suivi"], "statut": r["statut"], "message": message}
        return {**r, "message": message}
    finally:
        conn.close()


def _deja_recu(cle, u):
    """Réponse d'un signalement déjà reçu avec cette clé, ou None. La réponse a la même forme que la première fois."""
    if not cle:
        return None
    conn = _base()
    try:
        row = conn.execute("SELECT * FROM signalement WHERE cle_client=? ORDER BY id LIMIT 1", (str(cle)[:80],)).fetchone()
        if row is None:
            return None
        if u is None:
            return {"code_suivi": row["code_suivi"], "statut": row["statut"], "message": _message_citoyen(row["statut"], row["code_suivi"])}
        d = base._ligne(row)
        return {"id": row["id"], "code_suivi": row["code_suivi"], "score": row["score"], "statut": row["statut"], "motifs": d["motifs"],
                "message": _message(row["statut"], row["score"])}
    finally:
        conn.close()


def _message_citoyen(statut, code):
    suite = {"verifie": "Merci : votre signalement est vérifié.",
             "a_confirmer": "Merci : un agent va vérifier ce lieu sur place.",
             "rejete": "Votre signalement n'a pas pu être retenu (position ou informations inutilisables)."}[statut]
    return f"{suite} Conservez votre code de suivi : {code}."


def _message(statut, sc):
    return {"verifie": f"Signalement vérifié (confiance {sc:.0f}/100).",
            "a_confirmer": f"Signalement à confirmer sur place (confiance {sc:.0f}/100).",
            "rejete": f"Signalement rejeté (confiance {sc:.0f}/100) ; il est conservé avec ses motifs."}[statut]


@router.post("/signalements/import")
def importer_fichier(fichier: UploadFile = File(...), u=Depends(exiger_roles("brigade", "mairie"))):
    """Importe un fichier de collecte (campagne de terrain, export ODK/Kobo, couche SIG, jeu de test du jury) en CSV ou GeoJSON"""
    return _importer(fichier, u)


def _importer(fichier, u):
    """Importe un fichier CSV ou GeoJSON (taille et nombre de lignes limités par la config). Route synchrone :
    FastAPI l'exécute dans un fil séparé, le serveur reste disponible pendant l'import."""
    cfg = charger_config()
    maxi = cfg.verification.limites.fichier_octets_max
    contenu = fichier.file.read(maxi + 1)          # on ne lit jamais plus que la limite
    if len(contenu) > maxi:
        _refuser(f"Fichier trop volumineux : la limite est de {maxi // 1000} Ko.", 413)
    conn = _base()
    try:
        try:
            r = importation.importer(conn, fichier.filename, contenu, cfg, controles.reference(), utilisateur=u["identifiant"], secteur_defaut=u.get("zone"))
            securite.auditer(conn, u, "import_fichier", fichier.filename, {"acceptees": r["nb_acceptees"], "refusees": r["nb_refusees"]})
        except importation.LimiteDepassee as e:
            _refuser(str(e), 413)
        doublons.consolider(conn, cfg)
        return r
    finally:
        conn.close()


@router.get("/signalements/stats", dependencies=[Depends(exiger_roles("brigade", "mairie"))])
def statistiques(avec_essais: int = Query(0, description="1 : inclut les lots d'essai du jury")):
    """Comptes par statut et par motif de rejet (pour le tableau de bord)."""
    conn = _base()
    try:
        tous = base.lister_signalements(conn, avec_essais=bool(avec_essais))
        motifs = Counter()
        for s in tous:
            if s["statut"] == "rejete":
                for m in s["motifs"]:
                    if m["etat"] == controles.ECHEC:
                        motifs[m["controle"]] += 1
        par_statut = {k: 0 for k in base.STATUTS} | dict(Counter(s["statut"] for s in tous))
        filtre = "" if avec_essais else " AND essai=0"
        nb_synth = conn.execute(f"SELECT COUNT(*) FROM signalement WHERE synthetique=1{filtre}").fetchone()[0]
        nb_essais = conn.execute("SELECT COUNT(*) FROM signalement WHERE essai=1").fetchone()[0]
        return {"total": len(tous), "par_statut": par_statut, "par_motif_rejet": dict(motifs),
                "synthetique": nb_synth > 0, "nb_synthetiques": nb_synth, "nb_essais_masques": 0 if avec_essais else nb_essais,
                "avertissement": "Contient des données de démonstration synthétiques." if nb_synth else None,
                "nb_depotoirs": conn.execute("SELECT COUNT(*) FROM depotoir WHERE statut='verifie'").fetchone()[0],
                "lignes_refusees_a_l_import": conn.execute("SELECT COUNT(*) FROM ligne_refusee").fetchone()[0]}
    finally:
        conn.close()


@router.get("/signalements", dependencies=[Depends(exiger_roles("brigade", "mairie"))])
def lister(statut: Optional[str] = Query(None, description="verifie | a_confirmer | rejete"),
           avec_essais: int = Query(0, description="1 : inclut les lots d'essai du jury")):
    if statut is not None and statut not in base.STATUTS:
        raise HTTPException(400, f"Statut inconnu « {statut} » : choisir parmi {', '.join(base.STATUTS)}.")
    conn = _base()
    try:
        liste = base.lister_signalements(conn, statut, avec_essais=bool(avec_essais))
        return {"nombre": len(liste), "signalements": liste}
    finally:
        conn.close()


@router.post("/signalements/{sid}/revalider")
def revalider(sid: str, demande: Revalidation, u=Depends(exiger_roles("brigade"))):
    """Un agent change le statut à la main ; la décision est tracée dans le journal."""
    cfg = charger_config()
    if not sid.isascii() or not sid.isdigit() or not 1 <= int(sid) < 2**63:
        _refuser("Identifiant de signalement invalide : un entier positif est attendu.")
    sid = int(sid)
    for nom, v in (("motif", demande.motif), ("statut", demande.statut)):
        if len(v) > cfg.verification.limites.texte_max:
            _refuser(f"Le champ « {nom} » est trop long (maximum {cfg.verification.limites.texte_max} caractères).")
    conn = _base()
    try:
        # Garde-fou : une décision humaine ne peut pas valider un lieu IMPOSSIBLE (hors commune, (0,0), eau, aéroport).
        # L'agent doit alors saisir un nouveau signalement avec la bonne position. Rejeter reste toujours permis.
        if demande.statut in ("verifie", "a_confirmer"):
            actuel = base.lire_signalement(conn, sid)
            if actuel is not None:
                ref = controles.reference()
                for verif in (controles.controle_position, controles.controle_lieu):
                    r = verif(actuel, ref, cfg)
                    if r.etat == controles.ECHEC and r.gravite == controles.BLOQUANT:
                        raise HTTPException(409, f"Revalidation refusée : {r.motif} Une décision humaine ne peut pas valider un lieu impossible ; "
                                                 "saisissez un nouveau signalement avec la bonne position.")
        try:
            actuel = base.lire_signalement(conn, sid)
            if actuel and demande.statut == "verifie":                      # garde-fou : jamais valider un lieu impossible
                impossibles = [m["motif"] for m in actuel["motifs"] if m["controle"] in ("position", "lieu_possible") and m.get("gravite") == "bloquant"]
                if impossibles:
                    raise HTTPException(409, "Revalidation refusée : le lieu est impossible (" + " ".join(impossibles) + ") Vérifiez la position avant de valider.")
            s = base.revalider(conn, sid, demande.statut, u["identifiant"], demande.motif)
            securite.auditer(conn, u, "revalidation", sid, {"statut": demande.statut, "motif": demande.motif})
        except LookupError as e:
            raise HTTPException(404, str(e))
        except ValueError as e:
            raise HTTPException(400, str(e))
        doublons.consolider(conn, cfg)
        return {"signalement": s, "journal": base.journal_du_signalement(conn, sid)}
    finally:
        conn.close()


@router.get("/depotoirs", dependencies=[Depends(exiger_roles("brigade", "mairie", "precollecteur"))])
def depotoirs():
    """Dépotoirs consolidés (un tas = un dépotoir) au format GeoJSON, avec la confiance."""
    conn = _base()
    try:
        carte = doublons.lister_depotoirs(conn)
        for f in carte["features"]:
            f["properties"]["ref"] = securite.ref_depotoir(f["properties"]["id"])      # permet de donner un avis sur place
        return carte
    finally:
        conn.close()


@router.get("/export/osm", dependencies=[Depends(exiger_roles("mairie"))])
def export_osm(format: str = Query("json", description="json (les deux) | geojson | osm"),
               demo: int = Query(0, description="1 : autorise l'export de dépotoirs synthétiques (fichier de démonstration marqué)")):
    """Export des seuls dépotoirs vérifiés : GeoJSON et fichier .osm pour JOSM.
    Les dépotoirs synthétiques sont refusés (409) sauf ?demo=1."""
    conn = _base()
    try:
        exp = doublons.export_osm(conn, charger_config(), demo=bool(demo))
    except doublons.ExportSynthetiqueRefuse as e:
        raise HTTPException(409, str(e))
    finally:
        conn.close()
    if format == "osm":
        return Response(exp["osm"], media_type="application/xml",
                        headers={"Content-Disposition": "attachment; filename=oregdo_depotoirs.osm"})
    if format == "geojson":
        return exp["geojson"]
    if format != "json":
        raise HTTPException(400, "Format inconnu : choisir json, geojson ou osm.")
    return {"nombre": exp["nombre"], "geojson": exp["geojson"], "osm": exp["osm"]}


class CorpsPieges(BaseModel):
    signalements: Optional[list[Any]] = Field(None, description="Signalements à tester (mêmes champs que POST /signalements, + piege facultatif)")
    generer: Optional[int] = Field(None, description="Nombre de pièges variés à générer")
    graine: Optional[int] = Field(None, ge=0, le=10**9, description="Facultatif : rejoue exactement les mêmes pièges (démonstration reproductible)")


@router.post("/alea/pieges")
def lancer_pieges(corps: CorpsPieges, u=Depends(exiger_roles("mairie"))):     # épreuve en direct : mairie ou admin
    """Fait passer des signalements piégés par le VRAI pipeline. Renvoie `resultats` (verdict et motifs de chacun)
    et `resume` (vérifiés / à confirmer / rejetés). Les signalements sont conservés (source « jury », synthétiques)."""
    try:
        res = lot.verifier_pieges(corps.signalements, corps.generer, graine=corps.graine)
        conn = _base()
        try:
            securite.auditer(conn, u, "alea_pieges", None, res["resume"])
        finally:
            conn.close()
        return res
    except ValueError as e:
        raise HTTPException(422, str(e))
