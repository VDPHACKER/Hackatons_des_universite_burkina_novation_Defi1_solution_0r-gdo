"""Données de planification : îlots (demande), sites candidats, dépôt, CET ; ajout de quartiers."""
from dataclasses import dataclass, replace
from functools import lru_cache

import numpy as np
from shapely.geometry import Point, Polygon, shape

from ..config import COMMUNE_DEFAUT, charger_config
from ..geo import couche, vers_metrique
from .parametres import moteur
from .reseau import profil_geometrique, projeter


@dataclass(frozen=True)
class Donnees:
    ilots_xy: np.ndarray
    ilots_pop: np.ndarray        # habitants (avant facteur de population)
    ilots_ids: list
    ilots_profil: dict
    sites_xy: np.ndarray
    sites_cout: np.ndarray       # FCFA
    sites_cap_kg_j: np.ndarray
    sites_ids: list
    sites_profil: dict
    depot_xy: np.ndarray
    cet_xy: np.ndarray
    depot_profil: dict
    cet_profil: dict
    ilots_secteur: list = None   # secteur de chaque îlot
    ilots_type: list = None      # loti / non_loti


@lru_cache(maxsize=2)
def charger(commune: str = COMMUNE_DEFAUT) -> Donnees:
    ilots = couche("ilots", commune)
    sites = couche("sites_candidats", commune)
    infra = couche("infrastructures", commune)
    cen = vers_metrique(ilots, commune).geometry.centroid
    ixy = np.column_stack([cen.x.values, cen.y.values])
    sxy = projeter(sites.geometry.x.values, sites.geometry.y.values, commune)
    pt = {r.type: r.geometry for r in infra.itertuples()}
    dxy = projeter(pt["depot_camions"].x, pt["depot_camions"].y, commune)
    cxy = projeter(pt["cet"].x, pt["cet"].y, commune)
    return Donnees(ixy, ilots["population"].to_numpy(float), list(ilots["id"]), profil_geometrique(ixy, commune),
                   sxy, sites["cout_fcfa"].to_numpy(float), sites["capacite_kg_j"].to_numpy(float),
                   list(sites["id"]), profil_geometrique(sxy, commune), dxy, cxy,
                   profil_geometrique(dxy, commune), profil_geometrique(cxy, commune),
                   list(ilots["secteur"]), list(ilots["type_quartier"]))


def _grille(poly: Polygon, pas: float) -> np.ndarray:
    """Points d'une grille régulière à l'intérieur du polygone (au moins le centroïde)."""
    minx, miny, maxx, maxy = poly.bounds
    pts = [(x, y) for x in np.arange(minx + pas / 2, maxx, pas) for y in np.arange(miny + pas / 2, maxy, pas)
           if poly.contains(Point(x, y))]
    return np.array(pts) if pts else np.array([[poly.centroid.x, poly.centroid.y]])


def _concat_profil(a: dict, b: dict) -> dict:
    return {k: np.concatenate([a[k], b[k]]) for k in a}


def avec_quartiers(base: Donnees, quartiers: list, commune: str = COMMUNE_DEFAUT) -> Donnees:
    """Ajoute des quartiers {nom, population, polygone GeoJSON WGS84} : îlots (population répartie) + sites candidats."""
    if not quartiers:
        return base
    cfg = charger_config(commune)
    pas_ilot = moteur(cfg).resolution_nouveau_quartier_m
    d = base
    for q in quartiers:
        brut = shape(q["polygone"])
        parties = [brut] if brut.geom_type == "Polygon" else list(brut.geoms)
        polys = [Polygon(projeter([c[0] for c in p.exterior.coords], [c[1] for c in p.exterior.coords], commune)) for p in parties]
        cellules = np.vstack([_grille(p, pas_ilot) for p in polys])
        sites = np.vstack([_grille(p, cfg.planification.rayon_acces_pr_m) for p in polys])
        nom = q.get("nom", "NQ")
        k = len(sites)
        d = replace(
            d,
            ilots_xy=np.vstack([d.ilots_xy, cellules]),
            ilots_pop=np.concatenate([d.ilots_pop, np.full(len(cellules), float(q["population"]) / len(cellules))]),
            ilots_secteur=d.ilots_secteur + [nom] * len(cellules),
            ilots_type=d.ilots_type + [max(set(base.ilots_type), key=base.ilots_type.count)] * len(cellules),
            ilots_ids=d.ilots_ids + [f"{nom}-I{i}" for i in range(len(cellules))],
            ilots_profil=_concat_profil(d.ilots_profil, profil_geometrique(cellules, commune)),
            sites_xy=np.vstack([d.sites_xy, sites]),
            sites_cout=np.concatenate([d.sites_cout, np.full(k, np.median(base.sites_cout))]),
            sites_cap_kg_j=np.concatenate([d.sites_cap_kg_j, np.full(k, np.median(base.sites_cap_kg_j))]),
            sites_ids=d.sites_ids + [f"{nom}-C{i}" for i in range(k)],
            sites_profil=_concat_profil(d.sites_profil, profil_geometrique(sites, commune)),
        )
    return d
