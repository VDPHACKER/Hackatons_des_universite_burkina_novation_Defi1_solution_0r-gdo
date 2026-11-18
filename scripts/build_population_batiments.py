"""Répartit la population de la commune entre les îlots d'après les bâtiments réels (Open Buildings de Google).

    .venv\\Scripts\\python.exe scripts\\build_population_batiments.py [--sans-osm]

Méthode « dasymétrique » : la population officielle de la commune (RGPH 2019, packs/ouaga/commune_config.yaml) est répartie entre les
îlots proportionnellement à la SURFACE BÂTIE de chaque îlot (empreintes de bâtiments dont le centre tombe dans l'îlot). C'est une
modélisation, pas un recensement : chaque îlot porte `source_population` et `modelise`.

Entrées : data/raw/open_buildings/bfa_buildings.gdb.zip (HDX « Burkina Faso: Google Building Footprints », ODbL) ;
          data/raw/geofabrik/burkina-faso-latest.osm.pbf (bâtiments OpenStreetMap, pour recouper : corrélation îlot par îlot).
Sorties : packs/ouaga/ilots.geojson (population, menages, batiments, emprise_m2, source_population ; l'ancienne valeur synthétique
          est gardée dans `population_synthetique`) et packs/ouaga/population_batiments.json (méthode, effectifs, corrélation).
"""
import argparse
import json
import sys
import time
from pathlib import Path

import geopandas as gpd
import numpy as np
import pyogrio

RACINE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RACINE))
from oregdo.config import charger_config  # noqa: E402

GDB = RACINE / "data" / "raw" / "open_buildings" / "bfa_buildings.gdb.zip"
PBF = RACINE / "data" / "raw" / "geofabrik" / "burkina-faso-latest.osm.pbf"
ILOTS = RACINE / "packs" / "ouaga" / "ilots.geojson"
CONFIANCE_MIN = 0.70            # Open Buildings v3 : score de confiance de 0,65 à 1 ; 0,70 écarte les détections douteuses


def lire_open_buildings(bbox):
    t = time.time()
    # La géodatabase est lue directement dans l'archive (/vsizip/), filtrée par emprise : on ne décompresse pas 871 Mo.
    couches = pyogrio.list_layers(f"/vsizip/{GDB.as_posix()}")
    nom = couches[0][0]
    print(f"Open Buildings : couche « {nom} » ({len(couches)} couche(s))")
    gdf = pyogrio.read_dataframe(f"/vsizip/{GDB.as_posix()}", layer=nom, bbox=bbox, use_arrow=False)
    print(f"  {len(gdf)} bâtiments dans l'emprise ({time.time() - t:.0f} s) ; colonnes : {list(gdf.columns)}")
    return gdf


def lire_osm(bbox):
    t = time.time()
    gdf = pyogrio.read_dataframe(PBF, layer="multipolygons", bbox=bbox, where="building IS NOT NULL", use_arrow=False)
    print(f"Bâtiments OpenStreetMap : {len(gdf)} dans l'emprise ({time.time() - t:.0f} s)")
    return gdf[gdf.geometry.notna()]


def par_ilot(batiments: gpd.GeoDataFrame, ilots: gpd.GeoDataFrame, crs_m: str):
    """(nombre, surface en m²) de bâtiments par îlot, d'après le centre de chaque empreinte."""
    m = batiments.to_crs(crs_m)
    surfaces = m.geometry.area.to_numpy()
    centres = gpd.GeoDataFrame({"surface": surfaces}, geometry=m.geometry.centroid, crs=crs_m).to_crs(ilots.crs)
    jointure = gpd.sjoin(centres, ilots[["geometry"]], how="inner", predicate="within")
    g = jointure.groupby("index_right")["surface"].agg(["count", "sum"])
    n = np.zeros(len(ilots)); s = np.zeros(len(ilots))
    n[g.index.to_numpy()], s[g.index.to_numpy()] = g["count"].to_numpy(), g["sum"].to_numpy()
    return n, s


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--sans-osm", action="store_true", help="ne pas recouper avec les bâtiments OpenStreetMap")
    args = ap.parse_args()
    if not GDB.exists():
        sys.exit(f"Open Buildings absent : {GDB} (voir data/raw/open_buildings/URL.txt)")
    cfg = charger_config()
    ilots = gpd.read_file(ILOTS)
    if "population_synthetique" not in ilots.columns:
        ilots["population_synthetique"] = ilots["population"]            # on garde l'ancienne valeur, une seule fois
    x0, y0, x1, y1 = ilots.total_bounds
    bbox = (x0 - 0.01, y0 - 0.01, x1 + 0.01, y1 + 0.01)

    ob = lire_open_buildings(bbox)
    col_conf = next((c for c in ob.columns if c.lower() in ("confidence", "confiance")), None)
    avant = len(ob)
    if col_conf:
        ob = ob[ob[col_conf] >= CONFIANCE_MIN]
    print(f"  confiance >= {CONFIANCE_MIN} : {len(ob)} bâtiments retenus sur {avant}")
    n_ob, s_ob = par_ilot(ob, ilots, cfg.commune.crs_metrique)
    if s_ob.sum() <= 0:
        sys.exit("Aucun bâtiment ne tombe dans les îlots : vérifier le système de coordonnées.")

    pop_totale = float(cfg.demographie.population)
    menages_totaux = float(cfg.demographie.menages)
    pop = pop_totale * s_ob / s_ob.sum()
    stats = {"source": "Google Open Buildings v3 (HDX buildings-google-bfa, ODbL)", "confiance_min": CONFIANCE_MIN,
             "batiments_retenus": int(n_ob.sum()), "batiments_ecartes_confiance": int(avant - len(ob)),
             "emprise_totale_m2": round(float(s_ob.sum())), "population_repartie": round(pop_totale), "ilots": len(ilots),
             "ilots_sans_batiment": int((n_ob == 0).sum()), "date": time.strftime("%Y-%m-%d")}

    if not args.sans_osm and PBF.exists():
        osm = lire_osm(bbox)
        n_osm, s_osm = par_ilot(osm, ilots, cfg.commune.crs_metrique)
        pop_osm = pop_totale * s_osm / s_osm.sum()
        pleins = (s_ob > 0) | (s_osm > 0)
        stats["osm"] = {"batiments": int(n_osm.sum()), "emprise_totale_m2": round(float(s_osm.sum())),
                        "correlation_population_par_ilot": round(float(np.corrcoef(pop[pleins], pop_osm[pleins])[0, 1]), 3),
                        "ecart_relatif_median": round(float(np.median(np.abs(pop[pleins] - pop_osm[pleins]) / np.maximum(pop[pleins], 1))), 3)}
        print(f"Recoupement OSM : corrélation par îlot {stats['osm']['correlation_population_par_ilot']}, écart relatif médian {stats['osm']['ecart_relatif_median']}")

    ilots["population"] = np.round(pop).astype(int)
    ilots["menages"] = np.round(menages_totaux * s_ob / s_ob.sum()).astype(int)
    ilots["batiments"] = n_ob.astype(int)
    ilots["emprise_m2"] = np.round(s_ob).astype(int)
    ilots["source_population"] = "open_buildings"
    ilots["modelise"] = True
    ilots.to_file(ILOTS, driver="GeoJSON")
    (ILOTS.parent / "population_batiments.json").write_text(json.dumps(stats, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(stats, ensure_ascii=False, indent=2))
    print(f"Population par îlot : min {ilots['population'].min()}, médiane {int(ilots['population'].median())}, max {ilots['population'].max()}")


if __name__ == "__main__":
    main()
