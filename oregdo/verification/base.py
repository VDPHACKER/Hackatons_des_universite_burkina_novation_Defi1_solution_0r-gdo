"""Accès à la base SQLite (un seul fichier) : création, écriture, lecture, journal."""
import json
import os
import sqlite3
from datetime import datetime, timezone
from pathlib import Path

from ..config import RACINE

SCHEMA = Path(__file__).with_name("schema.sql")
STATUTS = ("verifie", "a_confirmer", "rejete")


def chemin_base() -> Path:
    """Chemin de la base : variable OREGDO_DB si définie (tests), sinon data/oregdo.db."""
    from ..config import COMMUNE_DEFAUT
    return Path(os.environ.get("OREGDO_DB") or RACINE / "data" / ("oregdo.db" if COMMUNE_DEFAUT == "ouaga" else f"oregdo_{COMMUNE_DEFAUT}.db"))


def maintenant() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


_PRETES: dict = {}     # base -> date de modification du fichier après initialisation : évite de rejouer le schéma à chaque requête


def ouvrir(chemin=None) -> sqlite3.Connection:
    """Ouvre (et crée si besoin) la base, avec le schéma à jour et les migrations douces."""
    chemin = Path(chemin) if chemin else chemin_base()
    chemin.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(chemin, check_same_thread=False, timeout=15)
    conn.row_factory = sqlite3.Row
    cle = str(chemin.resolve())
    if cle not in _PRETES or not chemin.exists() or chemin.stat().st_size == 0:
        _migrer(conn)        # d'abord : une ancienne base doit recevoir les colonnes avant que le schéma crée les index qui les utilisent
        conn.executescript(SCHEMA.read_text(encoding="utf-8"))
        _PRETES[cle] = True
    return conn


COLONNES_AJOUTEES = {"essai": "INTEGER NOT NULL DEFAULT 0", "photo_plausible": "INTEGER NOT NULL DEFAULT 0",
                     "exif_coherent": "INTEGER NOT NULL DEFAULT 0", "utilisateur": "TEXT", "code_suivi": "TEXT", "audio": "TEXT", "cle_client": "TEXT"}


def _migrer(conn):
    """Migration douce : ajoute les colonnes récentes à une base créée avec un ancien schéma (rien n'est perdu)."""
    collecte = {r["name"] for r in conn.execute("PRAGMA table_info(collecte)")}
    if collecte and "cle_client" not in collecte:       # avant la clé d'idempotence : l'index du schéma en a besoin
        conn.execute("ALTER TABLE collecte ADD COLUMN cle_client TEXT")
        conn.commit()
    if conn.execute("SELECT 1 FROM sqlite_master WHERE name='utilisateur'").fetchone():
        # Le rôle « enquêteur » n'existe plus (le sujet ne le prévoit pas) : un ancien compte devient agent de la brigade,
        # qui fait le travail de terrain et peut importer un fichier de collecte.
        if conn.execute("UPDATE utilisateur SET role='brigade' WHERE role='enqueteur'").rowcount:
            conn.commit()
    existantes = {r["name"] for r in conn.execute("PRAGMA table_info(signalement)")}
    if not existantes:      # base neuve : la table sera créée par le schéma avec toutes ses colonnes
        return
    for nom, definition in COLONNES_AJOUTEES.items():
        if nom not in existantes:
            conn.execute(f"ALTER TABLE signalement ADD COLUMN {nom} {definition}")
    conn.commit()


def _ligne(row) -> dict:
    d = dict(row)
    if "motifs" in d:
        d["motifs"] = json.loads(d["motifs"] or "[]")
    if "audio" in d:                                   # le nom du fichier reste interne : on n'expose que sa présence
        d["a_audio"] = bool(d.pop("audio"))
    return d


def ajouter_signalement(conn, sig: dict, score, statut, motifs, empreintes=(), synthetique=False, essai=False,
                        photo_plausible=False, exif_coherent=False, commit=True, utilisateur=None, code_suivi=None) -> int:
    """Enregistre un signalement DÉJÀ évalué, ses empreintes de photos et l'entrée de journal automatique."""
    cur = conn.execute(
        """INSERT INTO signalement (lat, lon, secteur, taille, nature, caniveau, accessibilite, enqueteur,
           appareil, horodatage, recu_le, source, nb_photos, score, statut, motifs, synthetique,
           essai, photo_plausible, exif_coherent, utilisateur, code_suivi)
           VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
        (sig.get("lat"), sig.get("lon"), sig.get("secteur"), sig.get("taille"), sig.get("nature"),
         None if sig.get("caniveau") is None else int(bool(sig["caniveau"])), sig.get("accessibilite"),
         sig.get("enqueteur"), sig.get("appareil"), sig.get("horodatage"), sig.get("recu_le") or maintenant(),
         sig.get("source", "application"), len(empreintes), score, statut,
         json.dumps(motifs, ensure_ascii=False), int(bool(synthetique)),
         int(bool(essai)), int(bool(photo_plausible)), int(bool(exif_coherent)), utilisateur, code_suivi))
    sid = cur.lastrowid
    conn.executemany("INSERT INTO photo (signalement_id, empreinte) VALUES (?,?)", [(sid, e) for e in empreintes])
    journaliser(conn, sid, None, statut, "automatique", f"Score {score:.0f}/100 calculé à la réception.")
    if commit:
        conn.commit()
    return sid


def journaliser(conn, sid, ancien, nouveau, agent, motif):
    conn.execute("INSERT INTO journal (signalement_id, ancien_statut, nouveau_statut, agent, motif, date) "
                 "VALUES (?,?,?,?,?,?)", (sid, ancien, nouveau, agent, motif, maintenant()))


def lire_signalement(conn, sid: int):
    row = conn.execute("SELECT * FROM signalement WHERE id=?", (sid,)).fetchone()
    return _ligne(row) if row else None


def lister_signalements(conn, statut=None, avec_essais=False) -> list[dict]:
    """Signalements (les lots d'essai du jury sont exclus sauf `avec_essais`)."""
    cond, args = [], []
    if statut:
        cond.append("statut=?"); args.append(statut)
    if not avec_essais:
        cond.append("essai=0")
    where = (" WHERE " + " AND ".join(cond)) if cond else ""
    return [_ligne(r) for r in conn.execute(f"SELECT * FROM signalement{where} ORDER BY id", args)]


def empreintes_connues(conn, avec_essais=True) -> list[tuple[int, int]]:
    """(identifiant du signalement, empreinte en entier) des photos déjà reçues."""
    filtre = "" if avec_essais else " JOIN signalement s ON s.id = p.signalement_id WHERE s.essai = 0"
    return [(r[0], int(r[1], 16)) for r in conn.execute(f"SELECT p.signalement_id, p.empreinte FROM photo p{filtre}")]


def revalider(conn, sid: int, statut: str, agent: str, motif: str) -> dict:
    """Changement manuel de statut, tracé dans le journal. Lève ValueError si la demande est invalide."""
    if statut not in STATUTS:
        raise ValueError(f"Statut inconnu « {statut} » : choisir parmi {', '.join(STATUTS)}.")
    if not agent or not agent.strip():
        raise ValueError("Le nom de l'agent qui revalide est obligatoire.")
    if not motif or not motif.strip():
        raise ValueError("Le motif de la revalidation est obligatoire.")
    actuel = lire_signalement(conn, sid)
    if actuel is None:
        raise LookupError(f"Signalement {sid} introuvable.")
    conn.execute("UPDATE signalement SET statut=? WHERE id=?", (statut, sid))
    journaliser(conn, sid, actuel["statut"], statut, agent.strip(), motif.strip())
    conn.commit()
    return lire_signalement(conn, sid)


def journal_du_signalement(conn, sid: int) -> list[dict]:
    return [dict(r) for r in conn.execute("SELECT * FROM journal WHERE signalement_id=? ORDER BY id", (sid,))]


def compter_par_statut(conn, avec_essais=False) -> dict:
    filtre = "" if avec_essais else " WHERE essai=0"
    return {r["statut"]: r["n"] for r in conn.execute(f"SELECT statut, COUNT(*) n FROM signalement{filtre} GROUP BY statut")}
