"""Réseau routier simplifié et pondération saisonnière.

Choix (justifié dans docs/05) : le pack ne contient que les routes principales (821 tronçons). Un graphe
routier complet n'aurait aucune valeur pour les pistes de quartier. On utilise donc :
  distance(i, j) = facteur_detour * distance_euclidienne(i, j) + surcoûts de raccord de i et de j.
Le « raccord » est la distance de chaque point à la route revêtue la plus proche : c'est le tronçon de piste.
En saison des pluies ce raccord est multiplié par facteur_cout_piste, ou par facteur_zone_inondable si le
point est à moins de rayon_zone_inondable_m de l'eau. Calcul vectorisé : quelques ms pour 2 000 x 330.
"""
from dataclasses import dataclass
from functools import lru_cache

import numpy as np
import shapely
from pyproj import Transformer
from scipy.spatial.distance import cdist
from shapely import STRtree

from ..config import COMMUNE_DEFAUT, charger_config
from ..geo import couche, vers_metrique
from . import graphe_routier
from .parametres import moteur

SURFACES_NON_REVETUES = {"unpaved", "ground", "dirt", "sand", "gravel", "earth"}


@dataclass(frozen=True)
class ContexteReseau:
    arbre_routes: STRtree
    arbre_eau: STRtree
    transfo: Transformer


@lru_cache(maxsize=4)
def contexte(commune: str = COMMUNE_DEFAUT) -> ContexteReseau:
    cfg = charger_config(commune)
    routes = vers_metrique(couche("routes", commune), commune)
    if "surface" in routes.columns:
        routes = routes[~routes["surface"].isin(SURFACES_NON_REVETUES)]
    eau = vers_metrique(couche("eau", commune), commune)
    eau = eau[eau.geometry.notna() & ~eau.geometry.is_empty]
    return ContexteReseau(
        STRtree(list(routes.geometry)), STRtree(list(eau.geometry)),
        Transformer.from_crs("EPSG:4326", cfg.commune.crs_metrique, always_xy=True))


def projeter(lon, lat, commune: str = COMMUNE_DEFAUT) -> np.ndarray:
    """(lon, lat) WGS84 vers un tableau (n, 2) en mètres."""
    x, y = contexte(commune).transfo.transform(np.atleast_1d(lon), np.atleast_1d(lat))
    return np.column_stack([x, y])


def deprojeter(xy, commune: str = COMMUNE_DEFAUT) -> list:
    """Tableau (n, 2) en mètres vers liste de [lon, lat] WGS84 (pour les GeoJSON)."""
    lon, lat = contexte(commune).transfo.transform(np.asarray(xy)[:, 0], np.asarray(xy)[:, 1], direction="INVERSE")
    return [[float(a), float(b)] for a, b in zip(lon, lat)]


def _distance_plus_proche(arbre: STRtree, xy: np.ndarray) -> np.ndarray:
    idx, dist = arbre.query_nearest(shapely.points(xy), return_distance=True, all_matches=False)
    sortie = np.full(len(xy), np.inf)
    sortie[idx[0]] = dist
    return sortie


def profil_geometrique(xy: np.ndarray, commune: str = COMMUNE_DEFAUT) -> dict:
    """Distance de chaque point à la route revêtue et à l'eau (indépendant de la saison)."""
    ctx = contexte(commune)
    return {"d_route": _distance_plus_proche(ctx.arbre_routes, xy),
            "d_eau": _distance_plus_proche(ctx.arbre_eau, xy)}


def surcout_raccord(profil: dict, saison_pluies: bool, commune: str = COMMUNE_DEFAUT, inondable_seul: bool = False) -> np.ndarray:
    """Mètres supplémentaires dus à la saison sur le raccord de chaque point (0 hors saison des pluies).

    inondable_seul=True : seules les zones inondables sont pénalisées (accès à pied/tricycle d'un ménage à son PR :
    une piste mouillée ralentit mais n'allonge pas la distance acceptée). Les camions, eux, subissent aussi
    la pénalité de piste.
    """
    d = profil["d_route"]
    if not saison_pluies:
        return np.zeros_like(d)
    sp = charger_config(commune).planification.saison_pluies
    facteur = np.where(profil["d_eau"] <= sp.rayon_zone_inondable_m,
                       sp.facteur_zone_inondable, 1.0 if inondable_seul else sp.facteur_cout_piste)
    return d * (facteur - 1.0)


def matrice_couts(xy_a, surcout_a, xy_b, surcout_b, commune: str = COMMUNE_DEFAUT, saison_pluies=None, acces=False, limite=None) -> np.ndarray:
    """Coût effectif en mètres entre deux jeux de points.

    Avec le graphe routier OSM du pack (voir graphe_routier.py) : plus court chemin sur les vraies routes ; la saison est alors
    portée par les tronçons, d'où `saison_pluies` (à fournir) et `acces` (accès à pied : seule la zone inondable compte).
    `limite` : distances au-delà sans intérêt pour l'appelant (calcul bien plus rapide). Sans graphe (ou sans `saison_pluies`) :
    distance à vol d'oiseau x facteur de détour + surcoûts de raccord, comme avant."""
    if saison_pluies is not None:
        g = graphe_routier.charger(commune)
        if g is not None:
            return g.matrice(xy_a, xy_b, bool(saison_pluies), acces, limite)
    detour = moteur(charger_config(commune)).facteur_detour
    return detour * cdist(xy_a, xy_b) + surcout_a[:, None] + surcout_b[None, :]


def est_accessible(profil: dict, saison_pluies: bool, commune: str = COMMUNE_DEFAUT) -> np.ndarray:
    """Hors zone inondable en saison des pluies : les camions n'y passent pas (point coupé)."""
    if not saison_pluies:
        return np.ones(len(profil["d_route"]), dtype=bool)
    sp = charger_config(commune).planification.saison_pluies
    return profil["d_eau"] > sp.rayon_zone_inondable_m
