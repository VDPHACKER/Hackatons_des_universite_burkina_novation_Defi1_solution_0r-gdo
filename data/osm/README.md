# Extrait OpenStreetMap - Ouagadougou

Provenance : API Overpass publique (overpass-api.de), requetes dans `scripts/fetch_osm.py`
(boite englobante S,W,N,E = 12.25,-1.65,12.50,-1.40), telechargement du 2026-11-16.
Convertis en GeoJSON (EPSG:4326) par ce script ; aucune modification des donnees.

| Fichier | Contenu | Objets |
|---|---|---|
| limites_admin.geojson | Relation OSM 5675756 "Ouagadougou" (admin_level=6), contours bruts en MultiLineString (ways "outer" non assembles en polygone) | 1 |
| routes_principales.geojson | highway = trunk / primary / secondary | 861 |
| plans_eau.geojson | natural=water, waterway=river/stream/canal, water=reservoir | 1129 |
| aeroport.geojson | Aeroport international (aerodrome, IATA OUA), terminaux, piste | 5 |

Non obtenu : `dechets_existants` (amenity=waste_*, landuse=landfill) - serveurs Overpass satures (502/504) au moment du test.
Les secteurs/arrondissements (admin_level 8-10) n'ont pas ete retournes par la requete ; a verifier/obtenir via HDX COD-AB (CC BY-IGO).

## Licence
(c) Contributeurs OpenStreetMap, licence Open Database License (ODbL) 1.0 - https://www.openstreetmap.org/copyright
Obligations : attribution visible "(c) OpenStreetMap contributors" ; toute base derivee rendue publique doit rester sous ODbL (share-alike).
