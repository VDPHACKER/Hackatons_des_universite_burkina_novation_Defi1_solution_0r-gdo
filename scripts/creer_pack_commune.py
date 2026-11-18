"""Crée le pack d'une nouvelle commune (packs/<code>/) à partir de données ouvertes : OpenStreetMap + Google Open Buildings.

    .venv\\Scripts\\python.exe scripts\\creer_pack_commune.py --code bobo --nom "Bobo-Dioulasso" --centre -4.2967 11.1771 \\
        --population 904920 --menages 201093 --arrondissements 7 --secteurs 33 \\
        --abonnement 0.373 --modes ramassage_prive=0.373,tas_immondices=0.201,fosses_fumieres=0.029,bac_a_ordures=0.110,rue=0.203,fosse_caniveau=0.048,autres=0.036
    .venv\\Scripts\\python.exe scripts\\build_osm_layers.py --commune bobo        # graphe routier + fond de carte

Méthode (sans limite administrative, absente de l'extrait OSM de beaucoup de communes burkinabè) :
  1. emprise urbanisée = cases de 500 m où Open Buildings compte assez de surface bâtie, composante connexe du centre ;
  2. îlots = ces cases ; population = total officiel (RGPH) réparti selon la surface bâtie (méthode dasymétrique, MODÉLISÉE) ;
  3. secteurs et arrondissements = regroupements k-means des îlots, aux nombres officiels : contours SYNTHÉTIQUES, dits comme tels ;
  4. eau, routes, aéroport = OpenStreetMap ; sites candidats, CET, dépôt = hypothèses [H] à confirmer avec la mairie.
Chaque objet généré porte `synthetique: true` sauf l'eau, les routes et l'aéroport.
Le fichier de configuration reprend celui d'Ouagadougou (tous les paramètres de simulation, marqués [H]) et remplace la démographie.
"""
import argparse
import json
import re
import sys
from pathlib import Path

import numpy as np
import pyogrio
from pyproj import Transformer
from shapely.geometry import Point, box, mapping
from shapely.ops import transform as sh_transform
from shapely.ops import unary_union
from sklearn.cluster import KMeans

RACINE = Path(__file__).resolve().parents[1]
PBF = RACINE / "data" / "raw" / "geofabrik" / "burkina-faso-latest.osm.pbf"
GDB = RACINE / "data" / "raw" / "open_buildings" / "bfa_buildings.gdb.zip"
CRS_M = "EPSG:32630"          # UTM 30N : Ouagadougou, Bobo-Dioulasso et l'ouest du Burkina
CASE_M = 500                  # côté d'un îlot synthétique
GRAINE = 20260116
ROUTES_PRINCIPALES = ("motorway", "trunk", "primary", "secondary", "tertiary")


def ecrire(dossier, nom, features):
    (dossier / nom).write_text(json.dumps({"type": "FeatureCollection", "features": features}, ensure_ascii=False), encoding="utf-8")
    print(f"  {nom}: {len(features)} objets")


def batiments(centre, rayon_deg, confiance_min=0.70):
    bbox = (centre[0] - rayon_deg, centre[1] - rayon_deg, centre[0] + rayon_deg, centre[1] + rayon_deg)
    print(f"Open Buildings dans {bbox} …")
    ob = pyogrio.read_dataframe(f"/vsizip/{GDB.as_posix()}", layer="bfa_buildings", bbox=bbox, use_arrow=False)
    n0 = len(ob)
    ob = ob[ob["confidence"] >= confiance_min]
    print(f"  {n0} bâtiments, {len(ob)} avec confiance >= {confiance_min}")
    m = ob.to_crs(CRS_M)
    c = m.geometry.centroid
    return np.column_stack([c.x.values, c.y.values]), m.geometry.area.to_numpy(), bbox


def composante_du_centre(actives, centre_idx):
    """Cases actives connexes (8 voisins) à la case du centre-ville."""
    vus, pile = set(), [centre_idx]
    while pile:
        c = pile.pop()
        if c in vus or c not in actives:
            continue
        vus.add(c)
        i, j = c
        pile.extend((i + a, j + b) for a in (-1, 0, 1) for b in (-1, 0, 1) if (a or b))
    return vus


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--code", required=True)
    ap.add_argument("--nom", required=True)
    ap.add_argument("--centre", type=float, nargs=2, metavar=("LON", "LAT"), required=True)
    ap.add_argument("--population", type=int, required=True, help="population officielle de l'emprise urbanisée (RGPH)")
    ap.add_argument("--menages", type=int, required=True)
    ap.add_argument("--arrondissements", type=int, required=True)
    ap.add_argument("--secteurs", type=int, required=True)
    ap.add_argument("--abonnement", type=float, required=True, help="part des ménages avec ramassage privé (RGPH)")
    ap.add_argument("--modes", required=True, help="modes d'évacuation des ordures, ex. ramassage_prive=0.373,tas_immondices=0.201,...")
    ap.add_argument("--rayon-deg", type=float, default=0.16, help="demi-côté de la zone de recherche autour du centre, en degrés")
    ap.add_argument("--seuil-bati-m2", type=float, default=7000, help="surface bâtie minimale d'une case de 500 m pour la compter urbanisée")
    ap.add_argument("--loti-km", type=float, default=3.5, help="[H] rayon autour du centre où les quartiers sont supposés lotis")
    ap.add_argument("--fuseau", default="Africa/Ouagadougou")
    ap.add_argument("--marque", help="nom de l'application affiché (défaut : Orẽgdo, le nom du produit)")
    a = ap.parse_args()
    dossier = RACINE / "packs" / a.code
    dossier.mkdir(parents=True, exist_ok=True)
    rng = np.random.default_rng(GRAINE)
    vers_m = Transformer.from_crs("EPSG:4326", CRS_M, always_xy=True)
    vers_ll = Transformer.from_crs(CRS_M, "EPSG:4326", always_xy=True)
    en_ll = lambda g: sh_transform(lambda x, y, z=None: vers_ll.transform(x, y), g)  # noqa: E731
    cx, cy = vers_m.transform(*a.centre)

    # 1. emprise urbanisée à partir des bâtiments
    xy, surf, bbox = batiments(a.centre, a.rayon_deg)
    ix, iy = np.floor(xy[:, 0] / CASE_M).astype(int), np.floor(xy[:, 1] / CASE_M).astype(int)
    cases = {}
    for i, j, s in zip(ix, iy, surf):
        e = cases.setdefault((int(i), int(j)), [0.0, 0])
        e[0] += float(s)
        e[1] += 1
    actives = {c for c, (s, _) in cases.items() if s >= a.seuil_bati_m2}
    centre_case = (int(np.floor(cx / CASE_M)), int(np.floor(cy / CASE_M)))
    if centre_case not in actives:      # le centre exact peut tomber sur une case peu bâtie : on prend la case active la plus proche
        centre_case = min(actives, key=lambda c: (c[0] - centre_case[0]) ** 2 + (c[1] - centre_case[1]) ** 2)
    urbaines = sorted(composante_du_centre(actives, centre_case))
    print(f"Cases urbanisées : {len(urbaines)} sur {len(actives)} actives ({len(urbaines) * CASE_M ** 2 / 1e6:.0f} km2)")

    # 2. eau (OSM) pour retirer les cases d'eau
    eau_gdf = pyogrio.read_dataframe(PBF, layer="multipolygons", bbox=bbox, where="natural = 'water'", use_arrow=False)
    eau_gdf = eau_gdf[eau_gdf.geometry.notna()]
    eau_m = eau_gdf.to_crs(CRS_M).geometry
    eau_union = unary_union(list(eau_m)) if len(eau_m) else None

    cellules = []
    for (i, j) in urbaines:
        poly = box(i * CASE_M, j * CASE_M, (i + 1) * CASE_M, (j + 1) * CASE_M)
        if eau_union is not None and eau_union.contains(poly.centroid):
            continue
        s, n = cases[(i, j)]
        cellules.append((poly, s, n))
    surf_tot = sum(s for _, s, _ in cellules)

    # 3. limite = union lissée des cases
    union = unary_union([p for p, _, _ in cellules]).buffer(250).buffer(-250).simplify(15)
    commune_ll = en_ll(union)
    ecrire(dossier, "commune.geojson", [{"type": "Feature", "geometry": mapping(commune_ll), "properties": {
        "nom": a.nom, "source": "emprise urbanisée déduite des bâtiments Google Open Buildings (limite administrative absente de l'extrait OSM)",
        "synthetique": True}}])

    # 4. îlots : population répartie selon la surface bâtie
    ilots, centres = [], []
    for k, (poly, s, n) in enumerate(cellules):
        c = poly.centroid
        d_km = float(np.hypot(c.x - cx, c.y - cy) / 1000)
        centres.append((c.x, c.y))
        ilots.append({"type": "Feature", "geometry": mapping(en_ll(poly)), "properties": {
            "id": f"I{k:04d}", "population": int(round(a.population * s / surf_tot)), "menages": int(round(a.menages * s / surf_tot)),
            "dist_centre_km": round(d_km, 2), "type_quartier": "loti" if d_km < a.loti_km else "non_loti", "batiments": int(n),
            "emprise_m2": int(round(s)), "source_population": "open_buildings", "modelise": True, "synthetique": True}})

    # 5. secteurs et arrondissements (regroupements k-means pondérés par la population)
    pts = np.array(centres)
    poids = np.array([f["properties"]["population"] for f in ilots], float) + 1
    km = KMeans(n_clusters=a.secteurs, n_init=5, random_state=GRAINE).fit(pts, sample_weight=poids)
    arr = KMeans(n_clusters=a.arrondissements, n_init=5, random_state=GRAINE).fit(km.cluster_centers_)
    for k, f in enumerate(ilots):
        s = km.labels_[k]
        f["properties"]["secteur"] = f"S{s + 1:02d}"
        f["properties"]["arrondissement"] = f"A{arr.labels_[s] + 1:02d}"
    ecrire(dossier, "ilots.geojson", ilots)
    secteurs = []
    for s in range(a.secteurs):
        morceaux = [cellules[k][0] for k in range(len(cellules)) if km.labels_[k] == s]
        g = unary_union(morceaux).buffer(5).buffer(-5)
        pop = sum(ilots[k]["properties"]["population"] for k in range(len(cellules)) if km.labels_[k] == s)
        secteurs.append({"type": "Feature", "geometry": mapping(en_ll(g)), "properties": {
            "id": f"S{s + 1:02d}", "nom": f"Secteur {s + 1}", "arrondissement": f"A{arr.labels_[s] + 1:02d}", "population": pop,
            "synthetique": True, "avertissement": "Découpage synthétique : à remplacer par les secteurs officiels"}})
    ecrire(dossier, "secteurs.geojson", secteurs)

    # 6. eau, aéroport, routes (OpenStreetMap)
    eau = []
    for g in eau_gdf.geometry:
        if g.geom_type in ("Polygon", "MultiPolygon") and g.intersects(commune_ll) and g.area > 1e-8:
            eau.append({"type": "Feature", "geometry": mapping(g.intersection(commune_ll)), "properties": {"nom": "", "source": "OSM", "synthetique": False}})
    ecrire(dossier, "eau.geojson", eau)
    aero = pyogrio.read_dataframe(PBF, layer="multipolygons", bbox=bbox, where="aeroway IN ('aerodrome','runway','terminal')", use_arrow=False)
    ecrire(dossier, "aeroport.geojson", [{"type": "Feature", "geometry": mapping(g), "properties": {"nom": "Aéroport", "source": "OSM", "synthetique": False}}
                                         for g in aero.geometry if g is not None and g.intersects(commune_ll)])
    lignes = pyogrio.read_dataframe(PBF, layer="lines", bbox=bbox, where="highway IS NOT NULL", use_arrow=False)
    routes = []
    for g, h, nom, tags in zip(lignes.geometry, lignes["highway"], lignes["name"], lignes["other_tags"]):
        if h in ROUTES_PRINCIPALES and g is not None and g.intersects(commune_ll):
            m = re.search(r'"surface"=>"([^"]*)"', tags) if isinstance(tags, str) else None
            routes.append({"type": "Feature", "geometry": mapping(g), "properties": {
                "highway": h, "name": nom if isinstance(nom, str) else "", **({"surface": m.group(1)} if m else {}), "source": "OSM"}})
    ecrire(dossier, "routes.geojson", routes)

    # 7. sites candidats de points de regroupement : les îlots les plus peuplés de chaque secteur [H]
    candidats, n = [], 0
    for s in range(a.secteurs):
        idx = sorted([k for k in range(len(cellules)) if km.labels_[k] == s], key=lambda k: -ilots[k]["properties"]["population"])[:6]
        for k in idx:
            c = cellules[k][0].centroid
            if eau_union is not None and eau_union.contains(c):
                continue
            candidats.append({"type": "Feature", "geometry": mapping(en_ll(c)), "properties": {
                "id": f"C{n:03d}", "secteur": f"S{s + 1:02d}", "cout_fcfa": int(rng.integers(600_000, 1_500_000)),
                "capacite_kg_j": int(rng.choice([3000, 5000, 8000])), "synthetique": True}})
            n += 1
    ecrire(dossier, "sites_candidats.geojson", candidats)

    # 8. infrastructures : POSITIONS HYPOTHÉTIQUES, à confirmer avec la mairie (aucune source ouverte trouvée)
    minx, miny, maxx, maxy = commune_ll.bounds
    cet = (minx + 0.15 * (maxx - minx), miny + 0.75 * (maxy - miny))
    ecrire(dossier, "infrastructures.geojson", [
        {"type": "Feature", "geometry": mapping(Point(cet)), "properties": {"id": "CET1", "nom": f"Centre d'enfouissement de {a.nom} (position hypothétique)",
         "type": "cet", "avertissement": "Coordonnées à confirmer avec la mairie", "synthetique": True}},
        {"type": "Feature", "geometry": mapping(Point(a.centre)), "properties": {"id": "DEP1", "nom": "Dépôt des camions (hypothèse)",
         "type": "depot_camions", "avertissement": "Hypothèse à confirmer", "synthetique": True}}])

    # 9. configuration : on reprend celle d'Ouagadougou (paramètres [H] de simulation) et on remplace l'identité et la démographie
    t = (RACINE / "packs" / "ouaga" / "commune_config.yaml").read_text(encoding="utf-8")
    modes = dict(x.split("=") for x in a.modes.split(","))
    t = t.replace("# Configuration du pack commune : Ouagadougou.", f"# Configuration du pack commune : {a.nom}. Créée par scripts/creer_pack_commune.py à partir de celle d'Ouagadougou :\n"
                  "# seules l'identité et la démographie changent ; TOUS les autres paramètres sont des hypothèses [H] héritées d'Ouagadougou, à recaler avec la mairie.")
    t = re.sub(r"(\n  code: )\w+", rf"\g<1>{a.code}", t, count=1)
    t = re.sub(r"(\n  nom: )[^\n]+", rf"\g<1>{a.nom}", t, count=1)
    marque = a.marque or "Orẽgdo"
    t = re.sub(r"(\n  marque: )[^\s#]+", rf"\g<1>{marque}", t, count=1)
    t = re.sub(r"(\n  fuseau: )[^\s#]+", rf"\g<1>{a.fuseau}", t, count=1)
    t = re.sub(r"(\n  population: )\d+[^\n]*", rf"\g<1>{a.population}               # [S] RGPH 2019 (emprise urbanisée)", t, count=1)
    t = re.sub(r"(\n  menages: )\d+[^\n]*", rf"\g<1>{a.menages}                 # [H] population / taille moyenne des ménages du RGPH 2019", t, count=1)
    t = re.sub(r"(\n  taux_abonnement: )[\d.]+[^\n]*", rf"\g<1>{a.abonnement}            # [S] part des ménages avec ramassage privé (RGPH 2019)", t, count=1)
    for cle, val in modes.items():
        t, k = re.subn(rf"(\n    {cle}: )[\d.]+", rf"\g<1>{val}", t, count=1)
        if not k:
            sys.exit(f"Mode d'évacuation inconnu dans la configuration : {cle}")
    # Ressources mises à l'échelle de la population (dimensionnement [H] d'Ouagadougou : 40 camions, 250 M FCFA, 14 tricycles x 55 secteurs, 60 agents)
    pop_ref = int(re.search(r"\n  population: (\d+)", (RACINE / "packs" / "ouaga" / "commune_config.yaml").read_text(encoding="utf-8")).group(1))
    r = a.population / pop_ref

    def remplacer(motif, valeur, commentaire):
        nonlocal t
        t, k = re.subn(motif, lambda m: f"{m.group(1)}{valeur}   # {commentaire}", t, count=1)
        if not k:
            sys.exit(f"Paramètre introuvable dans la configuration modèle : {motif}")
    echelle = f"[H] mis à l'échelle de la population depuis Ouagadougou (x{r:.2f})"
    remplacer(r"(\n    nombre: )\d+[^\n]*", max(1, round(40 * r)), echelle)
    remplacer(r"(\n  budget_pr_fcfa: )\d+[^\n]*", int(round(250_000_000 * r, -6)), echelle)
    remplacer(r"(\n    nombre_par_secteur: )\d+[^\n]*", max(1, round(14 * 55 * r / a.secteurs)), echelle + " et du nombre de secteurs")
    remplacer(r"(\n    effectif: )\d+[^\n]*", max(5, round(60 * r)), echelle)
    ab = a.abonnement
    remplacer(r"(\n    apport_volontaire_non_abonnes: )[\d.]+[^\n]*", round(float(modes["bac_a_ordures"]) / (1 - ab), 3),
              "[S dérivé] bac à ordures / (1 - abonnement), RGPH 2019")
    remplacer(r"(\n  fuite_vers_depotoir_si_pr_inaccessible: )[\d.]+[^\n]*", round((float(modes["tas_immondices"]) + float(modes["rue"])) / (1 - ab), 2),
              "[S dérivé] (tas + rue) / (1 - abonnement), RGPH 2019")
    (dossier / "commune_config.yaml").write_text(t, encoding="utf-8")
    print(f"Pack {a.code} écrit dans {dossier}. Population des îlots : {sum(f['properties']['population'] for f in ilots)}, "
          f"{len(ilots)} îlots, {a.secteurs} secteurs, {a.arrondissements} arrondissements.")


if __name__ == "__main__":
    main()
