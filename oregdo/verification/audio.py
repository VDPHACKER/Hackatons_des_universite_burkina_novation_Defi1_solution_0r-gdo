"""Message vocal joint à un signalement : pour celles et ceux qui écrivent peu (adaptation au contexte burkinabè).

La voix est une donnée personnelle : taille bornée, format vérifié sur les premiers octets (on ne fait pas confiance au nom ni au
type annoncé), écoute réservée à la brigade et à l'administration, EFFACEMENT automatique après `audio.conservation_jours`.
Seul le fichier est effacé : le signalement, lui, n'est jamais supprimé (règle du projet).
Le fichier vit à côté de la base (data/audio/<identifiant>.<extension>).
"""
import base64
import binascii
import re
from datetime import datetime, timedelta, timezone
from pathlib import Path

from . import base

TYPES = {"webm": "audio/webm", "ogg": "audio/ogg", "m4a": "audio/mp4"}


class AudioInvalide(ValueError):
    """Message vocal refusé (message en français, prêt à afficher)."""


def dossier() -> Path:
    return base.chemin_base().parent / "audio"


def _extension(octets: bytes) -> str | None:
    if octets[:4] == b"\x1a\x45\xdf\xa3":
        return "webm"                                  # Chrome, Edge, Android : WebM / Opus
    if octets[:4] == b"OggS":
        return "ogg"                                   # Firefox : Ogg / Opus
    if octets[4:8] == b"ftyp":
        return "m4a"                                   # Safari, iOS : MP4 / AAC
    return None


def decoder(valeur, cfg):
    """Base64 (ou « data:audio/...;base64,... ») -> (octets, extension), ou None si aucun audio. Lève AudioInvalide."""
    if valeur in (None, "", False):
        return None
    reglage = cfg.verification.audio
    if not reglage.actif:
        raise AudioInvalide("Les messages vocaux ne sont pas activés pour cette commune.")
    texte = str(valeur)
    if texte.startswith("data:"):
        texte = texte.split(",", 1)[-1]
    if len(texte) * 3 // 4 > reglage.octets_max + 3:
        raise AudioInvalide(f"Le message vocal est trop long : maximum {reglage.octets_max // 1000} Ko (environ {reglage.duree_max_s} secondes).")
    try:
        octets = base64.b64decode(re.sub(r"\s+", "", texte), validate=True)
    except (binascii.Error, ValueError):
        raise AudioInvalide("Le message vocal est illisible (encodage invalide).")
    if not octets or len(octets) > reglage.octets_max:
        raise AudioInvalide(f"Le message vocal est vide ou trop volumineux (maximum {reglage.octets_max // 1000} Ko).")
    ext = _extension(octets)
    if ext is None:
        raise AudioInvalide("Format audio non reconnu : le message vocal doit être enregistré par l'application (WebM, Ogg ou MP4).")
    return octets, ext


def enregistrer(conn, sid: int, octets: bytes, ext: str) -> None:
    d = dossier()
    d.mkdir(parents=True, exist_ok=True)
    nom = f"{int(sid)}.{ext}"
    (d / nom).write_bytes(octets)
    conn.execute("UPDATE signalement SET audio=? WHERE id=?", (nom, int(sid)))
    conn.commit()


def chemin(conn, sid: int):
    """(chemin du fichier, type MIME) du message vocal d'un signalement, ou None."""
    ligne = conn.execute("SELECT audio FROM signalement WHERE id=?", (int(sid),)).fetchone()
    if not ligne or not ligne["audio"]:
        return None
    p = dossier() / Path(ligne["audio"]).name         # .name : jamais de chemin fourni par la base
    return (p, TYPES.get(p.suffix.lstrip("."), "application/octet-stream")) if p.exists() else None


def purger(conn, cfg, maintenant: datetime | None = None) -> int:
    """Efface les messages vocaux plus anciens que `conservation_jours`. Renvoie le nombre de fichiers effacés."""
    limite = ((maintenant or datetime.now(timezone.utc)) - timedelta(days=cfg.verification.audio.conservation_jours)).isoformat(timespec="seconds")
    n = 0
    for r in conn.execute("SELECT id, audio FROM signalement WHERE audio IS NOT NULL AND recu_le < ?", (limite,)).fetchall():
        try:
            (dossier() / Path(r["audio"]).name).unlink(missing_ok=True)
        except OSError:
            continue                                   # fichier verrouillé : on réessaiera à la prochaine purge
        conn.execute("UPDATE signalement SET audio=NULL WHERE id=?", (r["id"],))
        n += 1
    conn.commit()
    return n
