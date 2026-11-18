"""Validation des entrées (bornes lues dans planification.limites) : toute valeur absurde donne un ValueError en français,
que l'API transforme en 422. Aucune de ces fonctions ne lève d'autre exception pour une entrée mal typée."""
import math
from functools import lru_cache

from ..config import COMMUNE_DEFAUT, charger_config


def limites(commune: str = COMMUNE_DEFAUT):
    return charger_config(commune).planification.limites


def nombre(nom: str, valeur, mini=None, maxi=None, entier: bool = False):
    """Valide un nombre fini (ni booléen, ni texte, ni null, ni nan/inf) dans [mini, maxi]. Renvoie int ou float."""
    if isinstance(valeur, bool) or not isinstance(valeur, (int, float)):
        raise ValueError(f"« {nom} » doit être un nombre (reçu : {_decrire(valeur)}).")
    if isinstance(valeur, float) and not math.isfinite(valeur):
        raise ValueError(f"« {nom} » doit être un nombre fini (nan et infini sont refusés).")
    if entier:
        if valeur != int(valeur):
            raise ValueError(f"« {nom} » doit être un nombre entier (reçu : {valeur}).")
        valeur = int(valeur)
    if mini is not None and valeur < mini or maxi is not None and valeur > maxi:
        raise ValueError(f"« {nom} » doit être compris entre {mini} et {maxi} (reçu : {valeur}).")
    return valeur


def _decrire(valeur) -> str:
    return "null" if valeur is None else type(valeur).__name__


@lru_cache(maxsize=2)
def _commune_metrique(commune: str):
    from ..geo import couche, vers_metrique
    return vers_metrique(couche("commune", commune), commune).geometry.union_all()


def valider_quartier(q, nb_existants: int = 0, commune: str = COMMUNE_DEFAUT) -> tuple:
    """Valide un quartier {nom, population, polygone GeoJSON}. Renvoie (quartier normalisé, avertissements)."""
    from shapely.geometry import Polygon, shape

    from .reseau import projeter
    lim = limites(commune)
    if not isinstance(q, dict):
        raise ValueError("Nouveau quartier : un objet avec « population » et « polygone » est attendu.")
    if nb_existants >= lim.nouveaux_quartiers_max:
        raise ValueError(f"Nouveau quartier : au plus {lim.nouveaux_quartiers_max} quartiers ajoutés.")
    if q.get("population") is None:
        raise ValueError("Nouveau quartier : la population est obligatoire.")
    pop = nombre("population du quartier", q["population"], lim.quartier_population[0], lim.quartier_population[1])
    nom = q.get("nom", f"NQ{nb_existants + 1}")
    if not isinstance(nom, str) or not nom.strip() or len(nom) > 60:
        raise ValueError("Nouveau quartier : le nom doit être un texte de 1 à 60 caractères.")
    geo = q.get("polygone")
    if not isinstance(geo, dict) or geo.get("type") not in ("Polygon", "MultiPolygon"):
        raise ValueError("Nouveau quartier : « polygone » doit être un GeoJSON de type Polygon ou MultiPolygon.")
    anneaux = [geo.get("coordinates")] if geo["type"] == "Polygon" else geo.get("coordinates")
    try:
        points = [p for poly in anneaux for anneau in poly for p in anneau]
        if not points or len(points) > lim.quartier_points_max:
            raise ValueError(f"Nouveau quartier : le polygone doit avoir de 1 à {lim.quartier_points_max} points.")
        for p in points:
            lon = nombre("longitude", p[0], -180, 180)
            lat = nombre("latitude", p[1], -90, 90)
            if len(p) not in (2, 3):
                raise ValueError("point mal formé")
    except (TypeError, IndexError, KeyError):
        raise ValueError("Nouveau quartier : coordonnées du polygone mal formées (attendu : [longitude, latitude]).") from None
    try:
        brut = shape(geo)
    except Exception:
        raise ValueError("Nouveau quartier : polygone GeoJSON invalide (anneaux fermés d'au moins 4 points).") from None
    if brut.is_empty or not brut.is_valid:
        raise ValueError("Nouveau quartier : polygone invalide (vide, auto-intersection ou anneau non fermé).")
    parties = [brut] if brut.geom_type == "Polygon" else list(brut.geoms)
    metriques = []
    for part in parties:
        xy = projeter([c[0] for c in part.exterior.coords], [c[1] for c in part.exterior.coords], commune)
        metriques.append(Polygon(xy))
    surface_km2 = sum(m.area for m in metriques) / 1e6
    if surface_km2 <= 0 or surface_km2 > lim.quartier_surface_km2_max:
        raise ValueError(f"Nouveau quartier : surface de {surface_km2:.2f} km2 hors limites (0 à {lim.quartier_surface_km2_max} km2).")
    xs = [c[0] for m in metriques for c in m.exterior.coords]
    ys = [c[1] for m in metriques for c in m.exterior.coords]
    if max(max(xs) - min(xs), max(ys) - min(ys)) > lim.quartier_etendue_km_max * 1000:
        raise ValueError(f"Nouveau quartier : emprise supérieure à {lim.quartier_etendue_km_max} km.")
    avert = []
    distance = min(m.distance(_commune_metrique(commune)) for m in metriques)
    if distance > lim.quartier_distance_commune_max_m:
        raise ValueError(f"Nouveau quartier : situé à {distance / 1000:.1f} km de la commune (maximum "
                         f"{lim.quartier_distance_commune_max_m / 1000:.0f} km).")
    if distance == 0 and not all(_commune_metrique(commune).contains(m) for m in metriques):
        avert.append(f"Le quartier « {nom} » dépasse en partie la limite de la commune.")
    if distance > 0:
        avert.append(f"Le quartier « {nom} » est à {distance:.0f} m de la limite de la commune : vérifier sa position.")
    return {"nom": nom.strip(), "population": float(pop), "polygone": geo}, avert
