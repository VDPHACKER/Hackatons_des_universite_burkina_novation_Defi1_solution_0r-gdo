r"""Fabrique les couches allégées de web/data/pack/ à partir de packs/ouaga/.

Objectif : page initiale légère et fonctionnement hors ligne (réseau lent et payant).
Coordonnées arrondies à 5 décimales (~1 m), géométries simplifiées, propriétés réduites.
Usage : .venv\Scripts\python.exe -I tests/e2e/build_light_pack.py
"""
import json
from pathlib import Path
from shapely.geometry import shape, mapping

RACINE = Path(__file__).resolve().parents[2]
SRC = RACINE / "packs" / "ouaga"
DST = RACINE / "web" / "data" / "pack"
DST.mkdir(parents=True, exist_ok=True)

PLAN = {  # fichier: (tolérance en degrés, propriétés gardées)
    "commune": (0.0002, ["nom"]),
    "secteurs": (0.0002, ["id", "nom", "arrondissement", "population"]),
    "eau": (0.0001, ["nom"]),
    "routes": (0.0002, ["highway", "name", "surface"]),
    "sites_candidats": (0, ["id", "secteur", "cout_fcfa", "capacite_kg_j"]),
    "infrastructures": (0, ["id", "nom", "type"]),
}


def arrondir(c):
    if isinstance(c[0], (int, float)):
        return [round(c[0], 5), round(c[1], 5)]
    return [arrondir(x) for x in c]


for nom, (tol, cles) in PLAN.items():
    d = json.loads((SRC / f"{nom}.geojson").read_text(encoding="utf8"))
    feats = []
    for f in d["features"]:
        g = shape(f["geometry"])
        if tol:
            g = g.simplify(tol, preserve_topology=True)
        if g.is_empty:
            continue
        geom = mapping(g)
        geom = {"type": geom["type"], "coordinates": arrondir(geom["coordinates"])}
        p = {k: f["properties"][k] for k in cles if k in f["properties"]}
        feats.append({"type": "Feature", "properties": p, "geometry": geom})
    out = DST / f"{nom}.geojson"
    out.write_text(json.dumps({"type": "FeatureCollection", "features": feats}, ensure_ascii=False, separators=(",", ":")), encoding="utf8")
    print(nom, len(feats), out.stat().st_size // 1024, "Ko")
