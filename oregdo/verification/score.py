"""Score de confiance (0 à 100), statut, et chaîne complète « un signalement entre, une décision sort ».

Formule (détails dans docs/04-module-verification.md) :
  points = somme des poids x fraction obtenue par contrôle
           (contrôle non applicable : poids - pénalité ; contrôle « neutre » : 0)
  score  = 100 x points / somme des poids des contrôles actifs  (+ bonus de corroboration, plafonné à 100)
  Un échec « bloquant » plafonne le score sous le seuil « à confirmer » (=> rejeté) ;
  un échec « grave » le plafonne sous le seuil « vérifié » (=> au mieux « à confirmer ») ;
  sans photo lisible ET sans corroboration par un 2e enquêteur, le score est plafonné à `sans_photo_plafond`.
"""
import json

from . import base, controles as c


REGLE_SANS_PHOTO = "regle_sans_photo"   # contrôles d'information (sans poids) : plafond appliqué
REGLE_NOUVEL_ID = "regle_nouvel_identifiant"
REGLE_GPS_IMPRECIS = "regle_gps_imprecis"


def precision_annoncee(sig):
    """Précision GPS annoncée par le téléphone (mètres), ou None si elle n'est pas fournie ou illisible."""
    try:
        p = float(str(sig.get("precision_m")).replace(",", "."))
    except (TypeError, ValueError):
        return None
    return p if p == p and 0 <= p < 1e6 else None


def poids_actifs(resultats, cfg) -> dict:
    poids = vars(cfg.verification.poids)
    actifs = {r.controle: poids[r.controle] for r in resultats if r.controle in poids}
    if any(r.controle == "classifieur_image" for r in resultats):
        actifs["classifieur_image"] = cfg.verification.classifieur_image.poids
    return actifs


def statut_pour(score, cfg) -> str:
    s = cfg.verification.seuils
    return "verifie" if score >= s.verifie else ("a_confirmer" if score >= s.a_confirmer else "rejete")


def calculer_score(resultats, cfg) -> tuple[float, str]:
    """Renvoie (score, statut) à partir de la liste des `Resultat`."""
    v = cfg.verification
    actifs = poids_actifs(resultats, cfg)
    points = 0.0
    bonus = 0.0
    for r in resultats:
        p = actifs.get(r.controle)
        if p is None:
            continue
        if r.etat == c.NON_APPLICABLE:
            points += max(0, p - v.non_applicable_penalite)
        elif r.etat != c.NEUTRE:
            points += p * r.fraction
        if r.bonus and r.etat == c.OK:
            bonus = v.corroboration.bonus_points
    score = 100 * points / sum(actifs.values()) + bonus
    if any(r.controle == REGLE_SANS_PHOTO for r in resultats):
        score = min(score, v.sans_photo_plafond)
    if any(r.controle == REGLE_NOUVEL_ID for r in resultats):
        score = min(score, v.nouvel_identifiant_plafond)
    if any(r.gravite == c.BLOQUANT for r in resultats):
        score = min(score, v.seuils.a_confirmer - 1)
    elif any(r.gravite == c.GRAVE for r in resultats):
        score = min(score, v.seuils.verifie - 1)
    score = round(max(0.0, min(100.0, score)), 1)
    return score, statut_pour(score, cfg)


def _exif_coherent(photos, sig, cfg) -> bool:
    r = c.controle_exif(photos, sig, cfg)
    return r.etat == c.OK


def identifiant_nouveau(sig, historique) -> bool:
    """Vrai si l'enquêteur ou l'appareil n'a jamais été vu (compte neuf ou identifiant jetable)."""
    return (not sig.get("enqueteur") or not any(h.get("enqueteur") == sig["enqueteur"] for h in historique)
            or not sig.get("appareil") or not any(h.get("appareil") == sig["appareil"] for h in historique))


def evaluer(sig, photos, historique, connues, ref, cfg, maintenant=None, octets=()):
    """Exécute les contrôles sans toucher à la base. `photos` = résultats de analyser_photo."""
    from .plausibilite import juger
    bonnes = [p for p in photos if juger(p, cfg)[0]]       # une photo non plausible compte comme absente
    plausible = bool(bonnes)
    exif_ok = _exif_coherent(bonnes, sig, cfg)
    resultats = [
        c.controle_position(sig, ref, cfg),
        c.controle_lieu(sig, ref, cfg),
        c.controle_doublons(sig, historique, cfg),
        c.controle_photo(photos, connues, cfg),
        c.controle_exif(bonnes, sig, cfg),
        c.controle_horodatage(sig, historique, cfg, maintenant),
        c.controle_corroboration(sig, historique, cfg, plausible or exif_ok),
    ]
    corrobore = any(r.controle == "corroboration" and r.etat == c.OK for r in resultats)
    if not plausible and not corrobore:
        raison = "Photo non plausible (" + next(juger(p, cfg)[1] for p in photos) + ")" if photos else "Sans photo"
        resultats.append(c.Resultat(REGLE_SANS_PHOTO, c.NEUTRE, 0, f"{raison} et sans confirmation par un 2e enquêteur : au mieux « à confirmer » (visite sur place nécessaire)."))
    elif not exif_ok and not corrobore and identifiant_nouveau(sig, historique):
        resultats.append(c.Resultat(REGLE_NOUVEL_ID, c.NEUTRE, 0, "Enquêteur ou appareil jamais vu auparavant et aucun EXIF cohérent : confiance plafonnée."))
    # GPS imprécis (relevé du réseau, ciel masqué) : la photo et ses EXIF portent la même erreur, ils ne la corrigent pas.
    # Le lieu doit être confirmé par un agent : au mieux « à confirmer ».
    prec, seuil = precision_annoncee(sig), getattr(cfg.verification, "precision_gps_max_m", 50)
    if prec is not None and prec > seuil:
        resultats.append(c.Resultat(REGLE_GPS_IMPRECIS, c.NEUTRE, 0, f"Position GPS imprécise (± {prec:.0f} m, au-delà de {seuil} m) : "
                                    "un agent doit confirmer l'emplacement exact (au mieux « à confirmer »).", c.GRAVE))
    if photos:
        verdicts = [juger(p, cfg) for p in photos]
        resultats.append(c.Resultat("photo_plausible", c.OK if plausible else c.ECHEC, 1.0 if plausible else 0.0,
                                    next((m for ok, m in verdicts if ok), verdicts[0][1]).capitalize() + "."))
    classe = c.controle_classifieur(list(octets), cfg)
    if classe is not None:
        resultats.append(classe)
    score, statut = calculer_score(resultats, cfg)
    return score, statut, resultats


def lire_historique(conn, avec_essais=False) -> list[dict]:
    """Signalements déjà reçus. Un signalement réel ne tient pas compte des lots d'essai ; un lot d'essai voit tout."""
    filtre = "" if avec_essais else " WHERE essai=0"
    rows = conn.execute("SELECT id, lat, lon, enqueteur, appareil, horodatage, statut, photo_plausible, exif_coherent "
                        f"FROM signalement{filtre}")
    return [dict(r) for r in rows]


def code_suivi() -> str:
    """Code de suivi remis au citoyen : 10 caractères lisibles, non devinables (sans 0/O/1/I)."""
    import secrets
    return "".join(secrets.choice("ABCDEFGHJKLMNPQRSTUVWXYZ23456789") for _ in range(10))


class Contexte:
    """Historique et empreintes chargés UNE fois pour un lot (import) : évite de relire la base à chaque ligne."""

    def __init__(self, conn, essai=False):
        self.historique = lire_historique(conn, avec_essais=essai)
        self.connues = base.empreintes_connues(conn, avec_essais=essai)


def verifier_et_enregistrer(conn, sig, photos_octets=(), ref=None, cfg=None, maintenant=None, synthetique=False,
                            essai=False, contexte=None, commit=True, utilisateur=None) -> dict:
    """Chaîne complète pour UN signalement : contrôles, score, enregistrement, journal. Ne plante pas sur une photo corrompue.
    `essai` : lot d'essai (pièges du jury) conservé mais exclu des statistiques, dépotoirs et plan."""
    from ..config import charger_config
    from .plausibilite import juger
    cfg = cfg or charger_config()
    ref = ref or c.reference()
    photos = [c.analyser_photo(o) for o in photos_octets]
    ctx = contexte or Contexte(conn, essai)
    score, statut, resultats = evaluer(sig, photos, ctx.historique, ctx.connues, ref, cfg, maintenant, photos_octets)
    motifs = [r.en_dict() for r in resultats]
    empreintes = [format(p["empreinte"], "016x") for p in photos if "empreinte" in p]
    plausible = any(m["controle"] == "photo_plausible" and m["etat"] == c.OK for m in motifs)
    exif_ok = any(m["controle"] == "exif" and m["etat"] == c.OK for m in motifs)
    sid = base.ajouter_signalement(conn, sig, score, statut, motifs, empreintes, synthetique, essai, plausible, exif_ok, commit=commit,
                                utilisateur=utilisateur, code_suivi=code_suivi())
    ctx.historique.append({"id": sid, "lat": sig.get("lat"), "lon": sig.get("lon"), "enqueteur": sig.get("enqueteur"),
                           "appareil": sig.get("appareil"), "horodatage": sig.get("horodatage"), "statut": statut,
                           "photo_plausible": int(plausible), "exif_coherent": int(exif_ok)})
    ctx.connues.extend((sid, int(e, 16)) for e in empreintes)
    if statut != "rejete" and sig.get("lat") is not None and any(m["controle"] == "corroboration" and m["etat"] == "ok" for m in motifs):
        _promouvoir_voisins(conn, sid, sig, cfg, essai, commit)
    code = conn.execute("SELECT code_suivi FROM signalement WHERE id=?", (sid,)).fetchone()[0]
    return {"id": sid, "score": score, "statut": statut, "motifs": motifs, "code_suivi": code}


def _promouvoir_voisins(conn, nouveau_id, sig, cfg, essai=False, commit=True):
    """Quand un 2e enquêteur confirme un tas, les voisins plafonnés pour « sans photo » sont recalculés."""
    from . import base as _b
    for h in _b.lister_signalements(conn, "a_confirmer", avec_essais=essai):
        if h["id"] == nouveau_id or h["lat"] is None or c.distance_m(sig["lat"], sig["lon"], h["lat"], h["lon"]) > cfg.verification.doublons.rayon_m:
            continue
        cle_h, cle_n = h["enqueteur"] or h["appareil"], sig.get("enqueteur") or sig.get("appareil")
        if not cle_h or not cle_n or cle_h == cle_n or h["appareil"] == sig.get("appareil"):
            continue
        motifs = h["motifs"]
        if not any(m["controle"] in (REGLE_SANS_PHOTO, REGLE_NOUVEL_ID) for m in motifs):
            continue
        nouveaux = []
        for m in motifs:
            if m["controle"] in (REGLE_SANS_PHOTO, REGLE_NOUVEL_ID):
                continue
            if m["controle"] == "corroboration":
                m = c.Resultat("corroboration", c.OK, 1, f"Confirmé a posteriori par un autre enquêteur (signalement n° {nouveau_id}) : bonus de confiance.", None, True).en_dict()
            nouveaux.append(m)
        sc, st = calculer_score([c.Resultat(**m) for m in nouveaux], cfg)
        if st != h["statut"]:
            conn.execute("UPDATE signalement SET score=?, statut=?, motifs=? WHERE id=?", (sc, st, json.dumps(nouveaux, ensure_ascii=False), h["id"]))
            _b.journaliser(conn, h["id"], h["statut"], st, "automatique", f"Confirmé par le signalement n° {nouveau_id} (autre enquêteur).")
    if commit:
        conn.commit()
