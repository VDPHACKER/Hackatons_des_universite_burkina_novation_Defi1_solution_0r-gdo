"""Chargement des couches du pack commune et projections métriques."""
from functools import lru_cache

import geopandas as gpd

from .config import COMMUNE_DEFAUT, charger_config


@lru_cache(maxsize=16)
def couche(nom: str, commune: str = COMMUNE_DEFAUT) -> gpd.GeoDataFrame:
    """Charge une couche du pack (WGS84). `nom` est une clé de commune.couches (ex. 'eau', 'secteurs')."""
    cfg = charger_config(commune)
    fichier = getattr(cfg.commune.couches, nom, None)
    if fichier is None:
        raise KeyError(f"Couche inconnue : {nom}")
    chemin = cfg.dossier_pack / fichier
    if not chemin.exists():
        raise FileNotFoundError(f"Fichier de couche absent : {chemin}")
    return gpd.read_file(chemin)


def vers_metrique(gdf: gpd.GeoDataFrame, commune: str = COMMUNE_DEFAUT) -> gpd.GeoDataFrame:
    """Projette en CRS métrique (distances en mètres)."""
    return gdf.to_crs(charger_config(commune).commune.crs_metrique)
