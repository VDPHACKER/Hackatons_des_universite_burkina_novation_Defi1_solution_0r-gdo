"""Traitement d'un LOT de signalements (ex. pièges du jury) dans le vrai pipeline de vérification.

Les signalements passent par EXACTEMENT les mêmes contrôles que ceux de l'application, sont enregistrés
(jamais supprimés, source = « jury », étiquetés synthétiques) et le détail est renvoyé.
"""
import base64
import binascii
import io
import random
from datetime import datetime, timedelta, timezone

from ..config import charger_config
from . import base, controles, score

MAX_LOT = 500
CAS_PIEGES = ("hors_commune", "eau", "piste", "zero_zero", "inversion", "futur", "rafale", "photo_reutilisee")


# ------------------------------------------------------------------ normalisation d'une entrée souple
def texte(v):
    """Chaîne, liste (jointe par virgule) ou nombre -> chaîne ; vide -> None."""
    if v is None:
        return None
    if isinstance(v, (list, tuple, set)):
        v = ", ".join(str(x).strip() for x in v if str(x).strip())
    v = str(v).strip()
    return v or None


def booleen(v):
    """True/False, 0/1, « oui/non/true/false » -> bool ; autre chose -> None."""
    if v is None or isinstance(v, bool):
        return v
    if isinstance(v, (int, float)):
        return bool(v)
    s = str(v).strip().lower()
    if s in ("oui", "o", "true", "vrai", "yes", "y", "1"):
        return True
    return False if s in ("non", "n", "false", "faux", "no", "0") else None


def nombre(v):
    try:
        return None if v is None else float(str(v).replace(",", "."))
    except ValueError:
        return None


def decoder_photo(p) -> bytes:
    if isinstance(p, (bytes, bytearray)):
        return bytes(p)
    if isinstance(p, dict):
        p = p.get("data") or p.get("base64") or p.get("contenu") or ""
    try:
        return base64.b64decode(str(p).split(",", 1)[-1], validate=False)
    except (binascii.Error, ValueError):
        return b""


def nombre_fini(v):
    """Nombre fini ou None (« inf », « nan », texte, vide : None)."""
    x = nombre(v)
    return x if x is not None and x == x and abs(x) != float("inf") else None


def normaliser(brut: dict) -> tuple[dict, list[bytes]]:
    """Dictionnaire souple (formes multiples acceptées) -> (signalement standard, photos en octets)."""
    sig = {k: texte(brut.get(k)) for k in ("secteur", "taille", "nature", "enqueteur", "appareil")}
    sig["accessibilite"] = texte(brut.get("accessibilite") if brut.get("accessibilite") is not None else brut.get("accessible"))
    sig["horodatage"] = texte(brut.get("horodatage") if brut.get("horodatage") is not None else brut.get("date_client"))
    sig.update(lat=nombre_fini(brut.get("lat")), lon=nombre_fini(brut.get("lon")), caniveau=booleen(brut.get("caniveau")))
    return sig, [decoder_photo(p) for p in (brut.get("photos") or [])]


# ------------------------------------------------------------------ le lot
def _motifs_lisibles(motifs, cfg) -> list[dict]:
    poids = {**vars(cfg.verification.poids), "classifieur_image": cfg.verification.classifieur_image.poids}
    sortie = []
    for m in motifs:
        p = poids.get(m["controle"])
        if p is None or m["etat"] == controles.NEUTRE:
            pts = 0.0                                   # règle d'information sans poids, ou contrôle neutre
        elif m["etat"] == controles.NON_APPLICABLE:
            pts = max(0, p - cfg.verification.non_applicable_penalite)
        else:
            pts = p * m["fraction"]
        sortie.append({"controle": m["controle"], "ok": m["etat"] in (controles.OK, controles.NON_APPLICABLE, controles.NEUTRE),
                       "etat": m["etat"], "message": m["motif"], "points": round(pts, 1), "gravite": m["gravite"]})
    return sortie


def verifier_lot(signalements, source="jury", conn=None, cfg=None, ref=None) -> list[dict]:
    """Fait passer chaque signalement (dict souple ; clé facultative `piege` ; `photos` en base64) par le pipeline.
    Renvoie `resultats` = [{id, statut, score, motifs:[{ok, message, points, ...}], piege:bool}].
    `piege` : valeur fournie par l'appelant, sinon vrai si le signalement a été rejeté."""
    cfg = cfg or charger_config()
    ref = ref or controles.reference()
    propre = conn is None
    conn = conn or base.ouvrir()
    try:
        resultats = []
        ctx = score.Contexte(conn, essai=True)            # un lot d'essai voit tout, mais on ne relit pas la base à chaque ligne
        for brut in signalements:
            brut = brut if isinstance(brut, dict) else {}
            sig, photos = normaliser(brut)
            sig["source"] = source
            r = score.verifier_et_enregistrer(conn, sig, photos, ref, cfg, synthetique=True, essai=True, contexte=ctx, commit=False)
            piege = brut["piege"] if "piege" in brut else r["statut"] == "rejete"
            resultats.append({"id": r["id"], "statut": r["statut"], "score": r["score"],
                              "motifs": _motifs_lisibles(r["motifs"], cfg), "piege": bool(piege)})
        conn.commit()          # lots d'essai : jamais consolidés en dépotoirs, donc sans effet sur le plan
        return resultats
    finally:
        if propre:
            conn.close()


def resume(resultats) -> dict:
    return {"verifies": sum(r["statut"] == "verifie" for r in resultats),
            "a_confirmer": sum(r["statut"] == "a_confirmer" for r in resultats),
            "rejetes": sum(r["statut"] == "rejete" for r in resultats),
            "pieges_verifies": sum(r["statut"] == "verifie" and r["piege"] for r in resultats)}


def verifier_pieges(signalements=None, generer=None, source="jury", conn=None) -> dict:
    """Point d'entrée commun de POST /api/alea/pieges et de l'aléa « signalements_pieges »."""
    if signalements is None and generer is None:
        raise ValueError("Fournir « signalements » (liste) ou « generer » (nombre de pièges à créer).")
    if signalements is None:
        signalements = generer_pieges(int(generer))
    if not isinstance(signalements, list) or not 1 <= len(signalements) <= MAX_LOT:
        raise ValueError(f"Il faut entre 1 et {MAX_LOT} signalements.")
    res = verifier_lot(signalements, source, conn)
    return {"resultats": res, "resume": resume(res)}


def generer_pieges(n: int, graine=None, maintenant=None) -> list[dict]:
    """N pièges variés (reproductibles pour une graine) : hors commune, eau, piste, (0,0), inversion lat/lon,
    futur, rafale, photo réutilisée. Aucun ne doit devenir « vérifié »."""
    from . import synthetique as syn
    if not 1 <= n <= MAX_LOT:
        raise ValueError(f"Le nombre de pièges doit être compris entre 1 et {MAX_LOT}.")
    rng = random.Random(graine if graine is not None else int(datetime.now().timestamp() * 1000) % 10**9)
    now = maintenant or datetime.now(timezone.utc)
    lieux, tag = syn.Lieux(rng, controles.reference()), f"{rng.randint(0, 10**6):06d}"
    sorties, i = [], 0

    def item(cas, lat, lon, k, photos=(), quand=None, appareil=None):
        sorties.append({"cas": cas, "piege": True, "lat": lat, "lon": lon, "enqueteur": f"JURY-{tag}-{k % 7}",
                        "appareil": appareil or f"APP-JURY-{tag}-{len(sorties)}", "nature": "mixte", "caniveau": "non",
                        "horodatage": (quand or now - timedelta(minutes=rng.randint(5, 600))).isoformat(),
                        "photos": [base64.b64encode(p).decode() for p in photos]})

    while len(sorties) < n:
        cas = CAS_PIEGES[i % len(CAS_PIEGES)]
        if cas == "hors_commune":
            item(cas, rng.uniform(13.5, 14.5), rng.uniform(1, 3), i)
        elif cas == "eau":
            item(cas, *lieux.dans_eau(), i)
        elif cas == "piste":
            item(cas, *lieux.sur_piste(), i)
        elif cas == "zero_zero":
            item(cas, 0.0, 0.0, i)
        elif cas == "inversion":
            la, lo = lieux.bon()
            item(cas, lo, la, i)
        elif cas == "futur":
            item(cas, *lieux.bon(), i, quand=now + timedelta(days=rng.randint(1, 60)))
        elif cas == "rafale":
            t0, app = now - timedelta(hours=3), f"APP-JURY-RAFALE-{tag}-{i}"
            for k in range(4):                                   # même appareil, 5 s d'écart, très loin les uns des autres
                item(cas, *lieux.bon(), i, quand=t0 + timedelta(seconds=5 * k), appareil=app)
        else:
            photo = syn.photo_synthetique(rng.randint(1, 10**8))
            item(cas + "_origine", 0.0, 0.0, i, [photo])         # l'original est rejeté (position nulle) mais sa photo est connue
            item(cas, *lieux.bon(), i, [_recompresser(photo, rng)])
        i += 1
    return sorties[:n]


def _recompresser(octets, rng) -> bytes:
    from PIL import Image
    img = Image.open(io.BytesIO(octets)).resize((rng.choice([128, 180, 200]),) * 2)
    tampon = io.BytesIO()
    img.save(tampon, "JPEG", quality=rng.choice([35, 45, 60]))
    return tampon.getvalue()
