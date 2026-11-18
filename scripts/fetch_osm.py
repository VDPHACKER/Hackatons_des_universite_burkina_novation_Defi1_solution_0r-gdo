"""Telecharge un extrait OSM de Ouagadougou via Overpass et ecrit du GeoJSON.
Usage: python scripts/fetch_osm.py   (stdlib uniquement)
Donnees (c) contributeurs OpenStreetMap, licence ODbL 1.0."""
import json, time, sys, urllib.request, urllib.parse, pathlib
OUT = pathlib.Path(__file__).resolve().parent.parent / "data" / "osm"
ENDPOINTS = ["https://overpass-api.de/api/interpreter",
             "https://overpass.private.coffee/api/interpreter",
             "https://overpass.kumi.systems/api/interpreter",
             "https://maps.mail.ru/osm/tools/overpass/api/interpreter"]
BBOX = "12.25,-1.65,12.50,-1.40"  # S,W,N,E  (~ville de Ouagadougou)
QUERIES = {
 "limites_admin": f'[out:json][timeout:60];(relation["boundary"="administrative"]["name"~"Ouagadougou"];relation["boundary"="administrative"]["admin_level"~"^(8|9|10)$"]({BBOX}););out geom;',
 "routes_principales": f'[out:json][timeout:90];way["highway"~"^(motorway|trunk|primary|secondary)$"]({BBOX});out geom;',
 "plans_eau": f'[out:json][timeout:60];(way["natural"="water"]({BBOX});relation["natural"="water"]({BBOX});way["waterway"~"^(river|stream|canal)$"]({BBOX});way["water"="reservoir"]({BBOX}););out geom;',
 "aeroport": f'[out:json][timeout:60];(way["aeroway"~"^(aerodrome|runway|terminal)$"]({BBOX});relation["aeroway"="aerodrome"]({BBOX});node["aeroway"="aerodrome"]({BBOX}););out geom;',
 "dechets_existants": f'[out:json][timeout:60];(nwr["amenity"~"^(waste_disposal|waste_transfer_station|recycling|waste_basket)$"]({BBOX});nwr["landuse"="landfill"]({BBOX}););out geom;',
}
def run(q):
    for rnd in range(4):
        for ep in ENDPOINTS:
            try:
                req = urllib.request.Request(ep, data=urllib.parse.urlencode({"data": q}).encode(),
                      headers={"User-Agent": "hackathon-ouaga-assainissement/0.1"})
                with urllib.request.urlopen(req, timeout=120) as r:
                    return json.load(r), ep
            except Exception as e:
                print("  echec", ep, str(e)[:80])
        time.sleep(5 * 2 ** rnd)
    return None, None
def ring(geom): return [[p["lon"], p["lat"]] for p in geom]
def to_features(elements):
    feats = []
    for e in elements:
        props = dict(e.get("tags", {})); props["@id"] = f'{e["type"]}/{e["id"]}'
        g = None
        if e["type"] == "node": g = {"type": "Point", "coordinates": [e["lon"], e["lat"]]}
        elif e["type"] == "way" and "geometry" in e:
            c = ring(e["geometry"])
            closed = len(c) > 3 and c[0] == c[-1] and ("highway" not in props)
            g = {"type": "Polygon", "coordinates": [c]} if closed else {"type": "LineString", "coordinates": c}
        elif e["type"] == "relation":
            lines = [ring(m["geometry"]) for m in e.get("members", []) if m.get("geometry") and m.get("role") in ("outer", "")]
            if lines: g = {"type": "MultiLineString", "coordinates": lines}  # contours bruts (non assembles)
        if g: feats.append({"type": "Feature", "properties": props, "geometry": g})
    return feats
if __name__ == "__main__":
    for name, q in QUERIES.items():
        data, ep = run(q)
        if data is None: print(name, "ECHEC"); continue
        fc = {"type": "FeatureCollection", "features": to_features(data["elements"])}
        (OUT / f"{name}.geojson").write_text(json.dumps(fc, ensure_ascii=False), encoding="utf-8")
        print(name, len(fc["features"]), "features via", ep)
