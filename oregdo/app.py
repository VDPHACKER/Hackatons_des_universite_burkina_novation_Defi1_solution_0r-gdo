"""Application FastAPI : monte les routeurs disponibles et sert la PWA et le pack commune.

Lancer : .venv\\Scripts\\python.exe -m uvicorn oregdo.app:app --port 8000
Les routeurs sont importés s'ils existent, pour que chaque module puisse être développé et testé seul.
"""
import importlib
import logging

from fastapi import FastAPI, HTTPException
from fastapi.middleware.gzip import GZipMiddleware
from fastapi.staticfiles import StaticFiles

from .config import RACINE, charger_config

journal = logging.getLogger("oregdo")
app = FastAPI(title="Orẽgdo", description="Outil libre d'aide à la décision pour l'assainissement")
# Les couches GeoJSON se compressent de 4 à 5 fois : décisif pour les connexions mobiles lentes (les rues de quartier pèsent ~10 Mo bruts).
app.add_middleware(GZipMiddleware, minimum_size=1000)

for nom in ("signalements", "plan", "portails", "notifications"):
    try:
        module = importlib.import_module(f"oregdo.api.{nom}")
        app.include_router(module.router, prefix="/api")
    except ModuleNotFoundError as e:
        if e.name != f"oregdo.api.{nom}":
            raise
        journal.warning("Routeur %s absent, ignoré", nom)


@app.on_event("startup")
def amorcer_administrateur():
    """Crée le premier administrateur depuis OREGDO_ADMIN_ID / OREGDO_ADMIN_MDP s'il n'existe pas (jamais de mot de passe dans un fichier)."""
    from .comptes import amorcer_admin_depuis_env
    if amorcer_admin_depuis_env():
        journal.info("Administrateur créé depuis l'environnement.")
    # Messages vocaux arrivés à échéance : effacés au démarrage (et à chaque dépôt). Jamais le signalement lui-même.
    from .config import charger_config
    from .verification import audio, base
    conn = base.ouvrir()
    try:
        n = audio.purger(conn, charger_config())
        if n:
            journal.info("%s message(s) vocal(aux) effacé(s) après la durée de conservation.", n)
    finally:
        conn.close()


@app.middleware("http")
async def revalider_les_fichiers_statiques(requete, suite):
    """Fichiers de l'interface : le navigateur doit revalider (ETag) avant de réutiliser une copie.
    Sans cela, une mise à jour de l'application peut rester invisible derrière un cache HTTP périmé."""
    reponse = await suite(requete)
    if not requete.url.path.startswith("/api/"):
        reponse.headers["Cache-Control"] = "no-cache"
    return reponse


@app.get("/api/commune")
def infos_commune():
    cfg = charger_config()
    return {"code": cfg.commune.code, "nom": cfg.commune.nom, "couches": vars(cfg.commune.couches)}


class CouchesSeulement(StaticFiles):
    """Sert uniquement les couches cartographiques (.geojson) du pack : jamais la configuration (jetons, réglages)."""

    async def get_response(self, path, scope):
        if not path.lower().endswith(".geojson"):
            raise HTTPException(404, "Fichier non public.")
        return await super().get_response(path, scope)


app.mount("/packs", CouchesSeulement(directory=RACINE / "packs"), name="packs")
_web = RACINE / "web"
if _web.exists():
    app.mount("/", StaticFiles(directory=_web, html=True), name="web")
