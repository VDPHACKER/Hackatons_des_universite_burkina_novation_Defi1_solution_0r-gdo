"""Le jury garde un jeu de test caché : l'import doit lire les formats courants des outils de collecte et des logiciels SIG,
et rejeter (sans planter) ce qui est absurde. Chaque cas est un fichier plausible."""
import json

import pytest

from oregdo.config import charger_config
from oregdo.verification import base, controles, importation

P = (12.3714, -1.5197)          # centre d'Ouagadougou


def geojson(geom, props=None):
    return json.dumps({"type": "FeatureCollection", "features": [{"type": "Feature", "geometry": geom, "properties": props or {"taille": "moyen"}}]}).encode()


@pytest.fixture
def importer(tmp_path, monkeypatch):
    monkeypatch.setenv("OREGDO_DB", str(tmp_path / "import.db"))
    cfg, ref = charger_config(), controles.reference()

    def faire(nom, contenu):
        conn = base.ouvrir()
        try:
            return importation.importer(conn, nom, contenu, cfg, ref)
        finally:
            conn.close()
    return faire


@pytest.mark.parametrize("nom,contenu,attendus", [
    ("virgule.csv", f"lat,lon,taille\n{P[0]},{P[1]},moyen\n".encode(), 1),
    ("point_virgule.csv", f"lat;lon\n{str(P[0]).replace('.', ',')};{str(P[1]).replace('.', ',')}\n".encode(), 1),
    ("tabulations.tsv.csv", f"latitude\tlongitude\n{P[0]}\t{P[1]}\n".encode(), 1),
    ("barres.csv", f"lat|lon\n{P[0]}|{P[1]}\n".encode(), 1),
    ("entetes.csv", f" Latitude , Longitude \n{P[0]},{P[1]}\n".encode(), 1),
    ("qgis_wkt.csv", f"WKT,taille\n\"POINT ({P[1]} {P[0]})\",moyen\n".encode(), 1),
    ("qgis_polygone.csv", f"wkt\n\"POLYGON (({P[1]} {P[0]}, {P[1] + 0.0003} {P[0]}, {P[1] + 0.0003} {P[0] + 0.0003}, {P[1]} {P[0]}))\"\n".encode(), 1),
    ("kobo.csv", f"geopoint,_submitted_by\n{P[0]} {P[1]} 300 5,awa\n".encode(), 1),
    ("latin1.csv", f"lat,lon,secteur\n{P[0]},{P[1]},Secteur é\n".encode("latin-1"), 1),
    ("bom.csv", ("﻿" + f"lat,lon\n{P[0]},{P[1]}\n").encode("utf-8"), 1),
    ("point.geojson", geojson({"type": "Point", "coordinates": [P[1], P[0]]}), 1),
    ("altitude.geojson", geojson({"type": "Point", "coordinates": [P[1], P[0], 305.0]}), 1),
    ("polygone.geojson", geojson({"type": "Polygon", "coordinates": [[[P[1], P[0]], [P[1] + 0.0003, P[0]], [P[1] + 0.0003, P[0] + 0.0003], [P[1], P[0]]]]}), 1),
    ("multipoint.geojson", geojson({"type": "MultiPoint", "coordinates": [[P[1], P[0]], [P[1] + 0.01, P[0] + 0.01]]}), 2),
    ("feature_seule.geojson", json.dumps({"type": "Feature", "geometry": {"type": "Point", "coordinates": [P[1], P[0]]}, "properties": {}}).encode(), 1),
    ("geometrie_seule.geojson", json.dumps({"type": "Point", "coordinates": [P[1], P[0]]}).encode(), 1),
])
def test_les_formats_courants_sont_lus(importer, nom, contenu, attendus):
    r = importer(nom, contenu)
    assert r["erreur_fichier"] is None and r["nb_acceptees"] == attendus and r["nb_refusees"] == 0


def test_un_polygone_donne_un_point_a_l_interieur_de_la_forme(importer):
    r = importer("zone.geojson", geojson({"type": "Polygon", "coordinates": [[[P[1], P[0]], [P[1] + 0.001, P[0]], [P[1] + 0.001, P[0] + 0.001], [P[1], P[0] + 0.001], [P[1], P[0]]]]}))
    conn = base.ouvrir(); s = base.lire_signalement(conn, r["acceptees"][0]["id"]); conn.close()
    assert P[0] < s["lat"] < P[0] + 0.001 and P[1] < s["lon"] < P[1] + 0.001


def test_des_coordonnees_inversees_sont_lues_puis_rejetees_par_la_verification(importer):
    r = importer("inverse.csv", f"lat,lon\n{P[1]},{P[0]}\n".encode())
    assert r["nb_acceptees"] == 1 and r["acceptees"][0]["statut"] == "rejete"         # enregistré pour l'audit, jamais dans le plan


def test_une_date_au_format_francais_ne_fait_pas_rejeter_un_signalement_valide(importer):
    r = importer("date.csv", f"lat,lon,date\n{P[0]},{P[1]},17/11/2026 08:30\n".encode())
    assert r["nb_acceptees"] == 1 and r["acceptees"][0]["statut"] != "rejete"


@pytest.mark.parametrize("nom,contenu", [
    ("vide.csv", b""), ("sans_position.csv", b"nom,couleur\na,b\n"), ("json_casse.geojson", b"{pas du json"),
    ("wkt_casse.csv", b"wkt\nPOINT (pas des nombres)\n"), ("geometrie_inconnue.geojson", json.dumps({"type": "Feature", "geometry": {"type": "Cercle", "coordinates": [1]}}).encode()),
])
def test_un_fichier_illisible_est_refuse_avec_une_explication_sans_planter(importer, nom, contenu):
    r = importer(nom, contenu)
    assert r["nb_acceptees"] == 0 and (r["erreur_fichier"] or r["refusees"])
