"""Construit le « pack commune » d'Ouagadougou à partir de l'extrait OSM.

Usage : python -I scripts/build_pack.py <racine_projet>

Ce qui vient d'OSM (réel) : limite de la commune, eau, aéroport, routes.
Ce qui est SYNTHÉTIQUE (étiqueté synthetique=true) : secteurs, îlots habités,
sites candidats de points de regroupement. Raison : les secteurs ne figurent pas
dans l'extrait OSM et Open Buildings pèse 871 Mo. Les chiffres de population
sont calés sur le RGPH 2019 (docs/01) mais la répartition spatiale est un modèle.
"""
import json
import sys
from pathlib import Path

import numpy as np
from shapely.geometry import Point, Polygon, mapping, shape
from shapely.ops import polygonize, unary_union
from sklearn.cluster import KMeans

RACINE = Path(sys.argv[1])
OSM = RACINE / "data" / "osm"
PACK = RACINE / "packs" / "ouaga"
PACK.mkdir(parents=True, exist_ok=True)
GRAINE = 20260116
rng = np.random.default_rng(GRAINE)

POP_TOTALE = 2_415_266      # RGPH 2019 (docs/01)
MENAGES_TOTAL = 502_938     # RGPH 2019
CENTRE = (-1.5337, 12.3686)  # (lon, lat) centre-ville, approximatif


def charger(nom):
    return json.load(open(OSM / f"{nom}.geojson", encoding="utf-8"))["features"]


def ecrire(nom, features):
    fc = {"type": "FeatureCollection", "features": features}
    (PACK / nom).write_text(json.dumps(fc, ensure_ascii=False), encoding="utf-8")
    print(f"{nom}: {len(features)} objets")


# 1. Commune : assemblage des lignes de contour en polygone
lignes = [shape(f["geometry"]) for f in charger("limites_admin")]
polys = list(polygonize(unary_union(lignes)))
if not polys:
    raise SystemExit("Impossible d'assembler la limite de la commune")
commune = max(polys, key=lambda p: p.area)
print("bbox commune", [round(v, 4) for v in commune.bounds])
ecrire("commune.geojson", [{"type": "Feature", "geometry": mapping(commune),
       "properties": {"nom": "Ouagadougou", "source": "OSM relation 5675756", "synthetique": False}}])

# 2. Eau (polygones seulement, coupés à la commune)
eau = []
for f in charger("plans_eau"):
    g = shape(f["geometry"])
    if g.geom_type in ("Polygon", "MultiPolygon") and g.intersects(commune) and g.area > 1e-8:
        eau.append({"type": "Feature", "geometry": mapping(g.intersection(commune)),
                    "properties": {"nom": f["properties"].get("name", ""), "source": "OSM", "synthetique": False}})
ecrire("eau.geojson", eau)
eau_union = unary_union([shape(f["geometry"]) for f in eau])

# 3. Aéroport : emprise + piste tamponnée (~40 m)
aero = []
for f in charger("aeroport"):
    g = shape(f["geometry"])
    if g.geom_type == "LineString":
        g = g.buffer(0.0004)
    aero.append({"type": "Feature", "geometry": mapping(g),
                 "properties": {"nom": f["properties"].get("name", "Aéroport"), "source": "OSM", "synthetique": False}})
ecrire("aeroport.geojson", aero)
aero_union = unary_union([shape(f["geometry"]) for f in aero])

# 4. Routes
routes = [f for f in charger("routes_principales") if shape(f["geometry"]).intersects(commune)]
ecrire("routes.geojson", routes)

# 5. Îlots synthétiques : grille d'environ 500 m, densité décroissante depuis le centre
pas = 0.0045  # ~500 m
minx, miny, maxx, maxy = commune.bounds
cellules = []
for x in np.arange(minx, maxx, pas):
    for y in np.arange(miny, maxy, pas):
        cellule = Polygon([(x, y), (x + pas, y), (x + pas, y + pas), (x, y + pas)])
        c = cellule.centroid
        if not commune.contains(c) or aero_union.contains(c):
            continue
        if eau_union.contains(c):
            continue
        d = np.hypot((c.x - CENTRE[0]) * 108.9, (c.y - CENTRE[1]) * 111.0)  # km
        densite = 9000 * np.exp(-d / 7.0) + 800
        densite *= rng.lognormal(0, 0.35)
        cellules.append((cellule, c, d, densite))
total = sum(d for *_, d in cellules)
facteur = POP_TOTALE / total
ilots = []
for i, (cell, c, d, dens) in enumerate(cellules):
    pop = int(dens * facteur)
    ilots.append({"type": "Feature", "geometry": mapping(cell), "properties": {
        "id": f"I{i:04d}", "population": pop, "menages": int(pop * MENAGES_TOTAL / POP_TOTALE),
        "dist_centre_km": round(float(d), 2),
        "type_quartier": "loti" if d < 6 else "non_loti",
        "synthetique": True}})
ecrire("ilots.geojson", ilots)

# 6. Secteurs synthétiques : 55 secteurs par k-means pondéré par la population, 12 arrondissements
centres = np.array([[c.x, c.y] for _, c, _, _ in cellules])
poids = np.array([i["properties"]["population"] for i in ilots], dtype=float)
km = KMeans(n_clusters=55, n_init=5, random_state=GRAINE).fit(centres, sample_weight=poids)
arr = KMeans(n_clusters=12, n_init=5, random_state=GRAINE).fit(km.cluster_centers_)
for i, il in enumerate(ilots):
    il["properties"]["secteur"] = f"S{km.labels_[i] + 1:02d}"
    il["properties"]["arrondissement"] = f"A{arr.labels_[km.labels_[i]] + 1:02d}"
ecrire("ilots.geojson", ilots)
secteurs = []
for k in range(55):
    morceaux = [shape(il["geometry"]) for il, lab in zip(ilots, km.labels_) if lab == k]
    g = unary_union(morceaux).buffer(0.0001).buffer(-0.0001)
    g = g.intersection(commune)
    pop = sum(il["properties"]["population"] for il, lab in zip(ilots, km.labels_) if lab == k)
    secteurs.append({"type": "Feature", "geometry": mapping(g), "properties": {
        "id": f"S{k + 1:02d}", "nom": f"Secteur {k + 1}", "arrondissement": f"A{arr.labels_[k] + 1:02d}",
        "population": pop, "synthetique": True,
        "avertissement": "Découpage synthétique : à remplacer par les secteurs officiels"}})
ecrire("secteurs.geojson", secteurs)

# 7. Sites candidats de points de regroupement : un par secteur au barycentre pondéré + points denses
candidats = []
n = 0
for k in range(55):
    idx = [i for i, lab in enumerate(km.labels_) if lab == k]
    cand = sorted(idx, key=lambda i: -ilots[i]["properties"]["population"])[:6]
    for i in cand:
        c = shape(ilots[i]["geometry"]).centroid
        if eau_union.contains(c):
            continue
        candidats.append({"type": "Feature", "geometry": mapping(c), "properties": {
            "id": f"C{n:03d}", "secteur": f"S{k + 1:02d}", "cout_fcfa": int(rng.integers(600_000, 1_500_000)),
            "capacite_kg_j": int(rng.choice([3000, 5000, 8000])), "synthetique": True}})
        n += 1
ecrire("sites_candidats.geojson", candidats)

# 8. Infrastructures : CET et dépôt de camions. POSITIONS APPROXIMATIVES À CONFIRMER.
nord_ouest = (minx + 0.15 * (maxx - minx), miny + 0.80 * (maxy - miny))
infra = [
    {"type": "Feature", "geometry": mapping(Point(nord_ouest)), "properties": {
        "id": "CET1", "nom": "CTVD de Polesgo (position approximative)", "type": "cet",
        "avertissement": "Coordonnées à confirmer avec la mairie", "synthetique": True}},
    {"type": "Feature", "geometry": mapping(Point(CENTRE)), "properties": {
        "id": "DEP1", "nom": "Dépôt des camions (hypothèse)", "type": "depot_camions",
        "avertissement": "Hypothèse à confirmer", "synthetique": True}},
]
ecrire("infrastructures.geojson", infra)
print("Population totale des îlots:", sum(i["properties"]["population"] for i in ilots))
