"""Construit, à partir de l'extrait OpenStreetMap local, le graphe routier réel et les couches du fond de carte.

    .venv\\Scripts\\python.exe scripts\\build_osm_layers.py [--graphe] [--fond]      (sans option : les deux)

Entrée : data/raw/geofabrik/burkina-faso-latest.osm.pbf (Geofabrik, ODbL, voir scripts/fetch_osm.py).
Sorties :
  packs/ouaga/graphe_routier.npz        graphe simplifié (intersections + tronçons) pour les distances des tournées
  web/data/pack/fond/*.geojson          couches visuelles : routes, quartiers, communes, repères, espaces verts, décharges OSM
Données © contributeurs OpenStreetMap, licence ODbL. Hypothèses [H] documentées dans docs/11.
"""
import argparse
import json
import re
import sys
import time
from pathlib import Path

import numpy as np
import pyogrio
import shapely
from pyproj import Transformer
from scipy.sparse import coo_matrix
from scipy.sparse.csgraph import connected_components
from shapely import STRtree

RACINE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RACINE))
from oregdo.config import charger_config  # noqa: E402
from oregdo.geo import couche, vers_metrique  # noqa: E402

PBF = RACINE / "data" / "raw" / "geofabrik" / "burkina-faso-latest.osm.pbf"
SORTIE_FOND = RACINE / "web" / "data" / "pack" / "fond"

# Routes praticables par un camion ou un tricycle. Les chemins piétons (path, footway, steps, cycleway) sont exclus.
CARROSSABLES = {"motorway", "trunk", "primary", "secondary", "tertiary", "unclassified", "residential", "service", "track",
                "living_street", "motorway_link", "trunk_link", "primary_link", "secondary_link", "tertiary_link"}
# [H] Revêtues par défaut : le réseau principal. Les rues de quartier sont supposées en terre sauf si `surface` dit le contraire.
REVETUES = {"motorway", "trunk", "primary", "secondary", "tertiary", "motorway_link", "trunk_link", "primary_link",
            "secondary_link", "tertiary_link"}
SURFACES_REVETUES = {"asphalt", "paved", "concrete", "paving_stones", "concrete:plates", "sett", "bricks"}
SURFACES_TERRE = {"unpaved", "ground", "dirt", "sand", "gravel", "earth", "compacted", "laterite"}
PRINCIPALES = {"motorway", "trunk", "primary", "secondary", "tertiary", "motorway_link", "trunk_link", "primary_link",
               "secondary_link", "tertiary_link"}
LOCALES = {"unclassified", "residential", "service", "track", "living_street"}


def tag(texte, cle):
    """Valeur d'une clé dans le champ `other_tags` d'OGR (« "cle"=>"valeur","autre"=>"v »), ou None."""
    if not isinstance(texte, str):
        return None
    m = re.search(r'"%s"=>"([^"]*)"' % re.escape(cle), texte)
    return m.group(1) if m else None


def emprise(commune="ouaga", marge=0.02):
    x0, y0, x1, y1 = couche("commune", commune).total_bounds
    return (x0 - marge, y0 - marge, x1 + marge, y1 + marge)


def arrondi(o, nd):
    if isinstance(o, (list, tuple)):
        return [arrondi(x, nd) for x in o]
    return round(o, nd) if isinstance(o, float) else o


def ecrire_geojson(nom, features, ndigits=5):
    SORTIE_FOND.mkdir(parents=True, exist_ok=True)
    chemin = SORTIE_FOND / nom
    for f in features:
        f["geometry"]["coordinates"] = arrondi(f["geometry"]["coordinates"], ndigits)
    chemin.write_text(json.dumps({"type": "FeatureCollection", "features": features}, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
    print(f"  {nom}: {len(features)} objets, {chemin.stat().st_size / 1e6:.2f} Mo")


def feature(geom, **props):
    return {"type": "Feature", "geometry": shapely.geometry.mapping(geom), "properties": {k: v for k, v in props.items() if v is not None}}


# ------------------------------------------------------------------ graphe routier
def construire_graphe(commune="ouaga"):
    cfg = charger_config(commune)
    t0 = time.time()
    print("Lecture des routes…")
    lignes = pyogrio.read_dataframe(PBF, layer="lines", bbox=emprise(commune), use_arrow=False)
    lignes = lignes[lignes["highway"].isin(CARROSSABLES) & lignes.geometry.notna()].reset_index(drop=True)
    print(f"  {len(lignes)} tronçons carrossables ({time.time() - t0:.0f} s)")
    surface = lignes["other_tags"].map(lambda s: tag(s, "surface"))
    revetue_voie = np.array([((h in REVETUES) or (s in SURFACES_REVETUES)) and s not in SURFACES_TERRE
                             for h, s in zip(lignes["highway"], surface)])

    geoms = np.asarray(lignes.geometry.values)
    lonlat, voie = shapely.get_coordinates(geoms, return_index=True)
    tr = Transformer.from_crs("EPSG:4326", cfg.commune.crs_metrique, always_xy=True)
    x, y = tr.transform(lonlat[:, 0], lonlat[:, 1])
    xy = np.column_stack([x, y])

    # Un nœud = un point partagé (OSM : deux voies qui se croisent partagent le même nœud, donc les mêmes coordonnées).
    cle = (np.round(lonlat[:, 0] * 1e7).astype(np.int64) + 30_000_000) * (1 << 30) + np.round(lonlat[:, 1] * 1e7).astype(np.int64)
    _, nid = np.unique(cle, return_inverse=True)
    nid = nid.ravel()
    meme_voie = voie[:-1] == voie[1:]
    longueur_seg = np.where(meme_voie, np.hypot(*(xy[1:] - xy[:-1]).T), 0.0)
    nb = nid.max() + 1
    degre = np.bincount(nid[:-1][meme_voie], minlength=nb) + np.bincount(nid[1:][meme_voie], minlength=nb)
    debut_fin = np.ones(len(nid), bool)                              # extrémités de voie : toujours conservées
    debut_fin[1:-1] = (voie[1:-1] != voie[:-2]) | (voie[1:-1] != voie[2:])
    garder = debut_fin | (degre[nid] != 2)
    pos = np.flatnonzero(garder)
    p, q = pos[:-1], pos[1:]
    ok = voie[p] == voie[q]
    p, q = p[ok], q[ok]
    cum = np.concatenate([[0.0], np.cumsum(longueur_seg)])
    longueur = cum[q] - cum[p]
    u, v = nid[p], nid[q]
    bon = (u != v) & (longueur > 0)
    p, q, u, v, longueur = p[bon], q[bon], u[bon], v[bon], longueur[bon]
    revetue = revetue_voie[voie[p]]
    # Arêtes parallèles : on ne garde que la plus courte (csgraph additionnerait les doublons).
    a, b = np.minimum(u, v), np.maximum(u, v)
    ordre = np.lexsort((longueur, b, a))
    a, b, p, q, u, v, longueur, revetue = (t[ordre] for t in (a, b, p, q, u, v, longueur, revetue))
    premier = np.ones(len(a), bool)
    premier[1:] = (a[1:] != a[:-1]) | (b[1:] != b[:-1])
    p, q, u, v, longueur, revetue = (t[premier] for t in (p, q, u, v, longueur, revetue))

    # Composante connexe principale : les îlots isolés ne servent à rien pour un camion.
    ids, inv = np.unique(np.concatenate([u, v]), return_inverse=True)
    inv = inv.ravel()
    eu, ev = inv[:len(u)], inv[len(u):]
    n = len(ids)
    _, comp = connected_components(coo_matrix((np.ones(len(eu)), (eu, ev)), shape=(n, n)), directed=False)
    principale = np.bincount(comp).argmax()
    dedans = (comp[eu] == principale) & (comp[ev] == principale)
    eu, ev, p, q, longueur, revetue = eu[dedans], ev[dedans], p[dedans], q[dedans], longueur[dedans], revetue[dedans]
    utiles, inv = np.unique(np.concatenate([eu, ev]), return_inverse=True)
    inv = inv.ravel()
    eu, ev = inv[:len(eu)].astype(np.int32), inv[len(eu):].astype(np.int32)
    ids_osm = ids[utiles]
    # Coordonnées d'un nœud : celles d'un des sommets qui le portent.
    premier_sommet = np.zeros(nb, np.int64)
    premier_sommet[nid[::-1]] = np.arange(len(nid))[::-1]
    noeud_xy = xy[premier_sommet[ids_osm]]

    # Distance de chaque tronçon à l'eau (zone inondable en saison des pluies), au milieu du tronçon.
    eau = vers_metrique(couche("eau", commune), commune)
    eau = eau[eau.geometry.notna() & ~eau.geometry.is_empty]
    arbre = STRtree(list(eau.geometry))
    idx, dist = arbre.query_nearest(shapely.points(xy[(p + q) // 2]), return_distance=True, all_matches=False)
    d_eau = np.full(len(p), 1e6)
    d_eau[idx[0]] = dist

    # Géométrie des tronçons : sommets p..q, stockés en float32 relatifs à une origine (précision du millimètre).
    origine = xy.min(axis=0)
    debut = np.concatenate([[0], np.cumsum(q - p + 1)])
    sommets = np.concatenate([np.arange(a_, b_ + 1) for a_, b_ in zip(p, q)])
    out = RACINE / "packs" / commune / "graphe_routier.npz"
    np.savez_compressed(out, noeuds_xy=noeud_xy, eu=eu, ev=ev, longueur=longueur.astype(np.float32), revetue=revetue,
                        d_eau=np.minimum(d_eau, 1e6).astype(np.float32), debut=debut.astype(np.int64),
                        geometrie=(xy[sommets] - origine).astype(np.float32), origine=origine)
    print(f"Graphe : {len(noeud_xy)} nœuds, {len(eu)} tronçons, {longueur.sum() / 1000:.0f} km "
          f"({100 * longueur[revetue].sum() / longueur.sum():.0f} % revêtus [H]) -> {out.name} ({out.stat().st_size / 1e6:.1f} Mo, {time.time() - t0:.0f} s)")


# ------------------------------------------------------------------ fond de carte
def construire_fond(commune="ouaga"):
    t0 = time.time()
    print("Lecture des routes pour le fond…")
    lignes = pyogrio.read_dataframe(PBF, layer="lines", bbox=emprise(commune), use_arrow=False)
    lignes = lignes[lignes.geometry.notna() & lignes["highway"].notna()]
    principales, locales = [], []
    for g, h, nom, tags in zip(lignes.geometry, lignes["highway"], lignes["name"], lignes["other_tags"]):
        if h in PRINCIPALES:
            principales.append(feature(g, c=h.replace("_link", ""), n=nom if isinstance(nom, str) else None, r=tag(tags, "ref")))
        elif h in LOCALES:
            locales.append(feature(g.simplify(0.00002), c="l"))     # ~2 m : invisible à l'écran, divise le poids du fichier
    ecrire_geojson("routes_principales.geojson", principales)
    ecrire_geojson("routes_locales.geojson", locales)

    print("Lecture des surfaces (sans bâtiments)…")
    mp = pyogrio.read_dataframe(PBF, layer="multipolygons", bbox=emprise(commune), where="building IS NULL", use_arrow=False)
    mp = mp[mp.geometry.notna()]
    # Communes voisines (limites administratives de niveau 6)
    adm = mp[mp["boundary"].eq("administrative") & mp["admin_level"].eq("6")]
    ecrire_geojson("communes.geojson", [feature(g.simplify(0.0003), nom=n) for g, n in zip(adm.geometry, adm["name"])], 4)
    # Espaces verts
    vert = mp[mp["leisure"].isin(["park", "garden", "recreation_ground"]) | mp["landuse"].isin(["forest", "grass", "recreation_ground", "cemetery"])
              | mp["natural"].isin(["wood"])]
    ecrire_geojson("verts.geojson", [feature(g.simplify(0.00003), t=next(x for x in (le, lu, na) if isinstance(x, str)))
                                     for g, le, lu, na in zip(vert.geometry, vert["leisure"], vert["landuse"], vert["natural"])
                                     if g.area > 5e-8], 5)
    # Décharges DÉJÀ cartographiées dans OSM (landuse=landfill) : à montrer et à recouper avec nos signalements.
    dec = mp[mp["landuse"].eq("landfill")]
    ecrire_geojson("decharges_osm.geojson", [feature(g.simplify(0.00002), nom=n if isinstance(n, str) else None, informel=tag(t, "informal"))
                                             for g, n, t in zip(dec.geometry, dec["name"], dec["other_tags"])], 5)
    # Repères : hôpitaux, marchés, mairies, universités, gares routières, écoles… (points et surfaces)
    points = pyogrio.read_dataframe(PBF, layer="points", bbox=emprise(commune), use_arrow=False)
    points = points[points.geometry.notna()]
    reperes = []
    types = {"hospital": 1, "clinic": 2, "university": 1, "townhall": 1, "marketplace": 2, "bus_station": 2, "police": 3, "school": 4, "college": 3, "pharmacy": 5}
    for g, n, t in zip(points.geometry, points["name"], points["other_tags"]):
        a = tag(t, "amenity")
        if a in types and isinstance(n, str):
            reperes.append(feature(g, nom=n, t=a, z=types[a]))
    sub = mp[mp["amenity"].isin(list(types)) & mp["name"].notna()]
    for g, n, a in zip(sub.geometry, sub["name"], sub["amenity"]):
        reperes.append(feature(g.representative_point(), nom=n, t=a, z=types[a]))
    ecrire_geojson("reperes.geojson", reperes)
    # Quartiers (points nommés place=suburb|neighbourhood|quarter) et villes proches
    lieux = []
    for g, n, pl in zip(points.geometry, points["name"], points["place"]):
        if pl in {"city", "town", "suburb", "neighbourhood", "quarter", "village"} and isinstance(n, str):
            lieux.append(feature(g, nom=n, t=pl))
    for g, n, pl in zip(mp.geometry, mp["name"], mp["place"]):
        if pl in {"suburb", "neighbourhood", "quarter", "town", "city"} and isinstance(n, str):
            lieux.append(feature(g.representative_point(), nom=n, t=pl))
    ecrire_geojson("lieux.geojson", lieux)
    print(f"Fond de carte terminé ({time.time() - t0:.0f} s).")


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--graphe", action="store_true")
    ap.add_argument("--fond", action="store_true")
    ap.add_argument("--commune", default="ouaga", help="code du pack (packs/<code>) ; le fond va dans web/data/packs/<code>/fond sauf pour ouaga")
    a = ap.parse_args()
    if not PBF.exists():
        sys.exit(f"Extrait OpenStreetMap absent : {PBF} (voir scripts/fetch_osm.py)")
    if a.commune != "ouaga":
        SORTIE_FOND = RACINE / "web" / "data" / "packs" / a.commune / "fond"
    if a.graphe or not a.fond:
        construire_graphe(a.commune)
    if a.fond or not a.graphe:
        construire_fond(a.commune)
