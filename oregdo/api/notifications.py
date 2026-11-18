"""Centre de notifications des agents (brigade, mairie) : déduit du journal des décisions, des avis de voisins et des interventions.

Aucune file à synchroniser : chaque événement existe déjà en base. On ne mémorise que la dernière date de lecture par compte.
Les données de démonstration (synthétiques) et les lots d'essai du jury ne notifient personne.
"""
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends

from ..securite import exiger_roles
from ..verification import base

router = APIRouter(tags=["notifications"])
JOURS = 14          # on ne remonte pas plus loin : une notification ancienne n'est plus une alerte
MAXI = 30


def _depuis() -> str:
    return (datetime.now(timezone.utc) - timedelta(days=JOURS)).isoformat(timespec="seconds")


def _evenements_brigade(conn, depuis):
    """À vérifier sur place : signalements arrivés au statut « à confirmer » (décision automatique)."""
    for r in conn.execute("""SELECT j.id, j.date, s.id sid, s.secteur FROM journal j JOIN signalement s ON s.id = j.signalement_id
                             WHERE j.nouveau_statut='a_confirmer' AND j.agent='automatique' AND j.date>=? AND s.synthetique=0 AND s.essai=0""", (depuis,)):
        lieu = f" ({r['secteur']})" if r["secteur"] else ""
        yield {"cle": f"j{r['id']}", "date": r["date"], "type": "a_verifier", "signalement_id": r["sid"], "lien": "#/brigade",
               "titre": "Signalement à vérifier sur place", "texte": f"Le signalement n° {r['sid']}{lieu} attend la visite d'un agent."}


def _evenements_mairie(conn, depuis):
    """Nouveaux dépotoirs vérifiés, décisions des agents, interventions."""
    for r in conn.execute("""SELECT j.id, j.date, j.agent, s.id sid, s.secteur FROM journal j JOIN signalement s ON s.id = j.signalement_id
                             WHERE j.nouveau_statut='verifie' AND j.date>=? AND s.synthetique=0 AND s.essai=0""", (depuis,)):
        lieu = f" ({r['secteur']})" if r["secteur"] else ""
        if r["agent"] == "automatique":
            texte = f"Le signalement n° {r['sid']}{lieu} a passé les contrôles automatiques."
        else:
            texte = f"Un agent a validé le signalement n° {r['sid']}{lieu} après vérification."
        yield {"cle": f"j{r['id']}", "date": r["date"], "type": "verifie", "signalement_id": r["sid"], "lien": "#/carte",
               "titre": "Nouveau dépotoir vérifié", "texte": texte}
    for r in conn.execute("SELECT id, date, depotoir_id FROM avis WHERE type='disparu' AND date>=?", (depuis,)):
        yield {"cle": f"a{r['id']}", "date": r["date"], "type": "disparu", "signalement_id": None, "lien": "#/mairie",
               "titre": "Un voisin dit que le tas a disparu", "texte": f"Avis sur le dépotoir n° {r['depotoir_id']} : à confirmer avant de le retirer du plan."}
    for r in conn.execute("SELECT id, date, depotoir_id, type FROM intervention WHERE date>=?", (depuis,)):
        quoi = "Sensibilisation" if r["type"] == "sensibilisation" else "Sanction"
        yield {"cle": f"i{r['id']}", "date": r["date"], "type": "intervention", "signalement_id": None, "lien": "#/brigade",
               "titre": f"{quoi} effectuée", "texte": f"La brigade est intervenue sur le dépotoir n° {r['depotoir_id']}."}


SOURCES = {"brigade": _evenements_brigade, "mairie": _evenements_mairie, "admin": _evenements_mairie}


def evenements(conn, role: str) -> list[dict]:
    source = SOURCES.get(role)
    if source is None:
        return []
    liste = sorted(source(conn, _depuis()), key=lambda e: e["date"], reverse=True)
    return liste[:MAXI]


def _derniere_lecture(conn, utilisateur: str):
    r = conn.execute("SELECT vu_le FROM notification_lue WHERE utilisateur=?", (utilisateur,)).fetchone()
    return r["vu_le"] if r else None


@router.get("/notifications")
def lister(u=Depends(exiger_roles("brigade", "mairie"))):
    """Événements récents pour le rôle du compte, avec le nombre de non lus."""
    conn = base.ouvrir()
    try:
        liste = evenements(conn, u["role"])
        vu = _derniere_lecture(conn, u["identifiant"])
        for e in liste:
            e["non_lu"] = vu is None or e["date"] > vu
        return {"non_lues": sum(e["non_lu"] for e in liste), "evenements": liste}
    finally:
        conn.close()


@router.post("/notifications/lues")
def marquer_lues(u=Depends(exiger_roles("brigade", "mairie"))):
    """Marque tout comme lu (conserve la date de lecture, jamais les événements eux-mêmes)."""
    conn = base.ouvrir()
    try:
        conn.execute("INSERT INTO notification_lue (utilisateur, vu_le) VALUES (?,?) ON CONFLICT(utilisateur) DO UPDATE SET vu_le=excluded.vu_le",
                     (u["identifiant"], base.maintenant()))
        conn.commit()
        return {"non_lues": 0}
    finally:
        conn.close()
