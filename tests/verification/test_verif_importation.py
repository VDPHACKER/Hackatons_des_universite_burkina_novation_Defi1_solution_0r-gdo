"""Tests de l'import : fichiers mal formés, sans photo, lignes piégées."""
import json

import pytest

from oregdo.verification import base, importation


@pytest.fixture
def conn(tmp_path):
    return base.ouvrir(tmp_path / "t.db")


def csv_de(p, extra=""):
    return ("lat,lon,secteur,enqueteur,appareil,horodatage\n"
            f"{p['lat']},{p['lon']},{p['secteur']},E1,A1,2020-01-01T10:00:00\n" + extra).encode()


def test_csv_sans_photo_est_traite(conn, bons_points, ref, cfg):
    r = importation.importer(conn, "a.csv", csv_de(bons_points[0]), cfg, ref)
    assert r["nb_acceptees"] == 1 and r["nb_refusees"] == 0
    # valide mais plafonné : sans photo ni 2e enquêteur, au mieux « à confirmer »
    assert r["acceptees"][0]["statut"] == "a_confirmer"


def test_csv_ligne_mal_formee_refusee_le_reste_passe(conn, bons_points, ref, cfg):
    p = bons_points[1]
    extra = "12.3,seulement,deux\n" f"abc,{p['lon']},x,E2,A2,2020-01-01\n" f"{p['lat']},{p['lon']},{p['secteur']},E3,A3,2020-01-01T10:00:00\n"
    r = importation.importer(conn, "b.csv", csv_de(bons_points[0], extra), cfg, ref)
    assert r["nb_acceptees"] == 2 and r["nb_refusees"] == 2
    assert all(x["raison"] for x in r["refusees"])
    assert conn.execute("SELECT COUNT(*) FROM ligne_refusee").fetchone()[0] == 2


def test_csv_points_virgule_et_virgule_decimale(conn, bons_points, ref, cfg):
    p = bons_points[2]
    contenu = f"latitude;longitude;secteur\n{str(p['lat']).replace('.', ',')};{str(p['lon']).replace('.', ',')};{p['secteur']}\n"
    assert importation.importer(conn, "c.csv", contenu.encode(), cfg, ref)["nb_acceptees"] == 1


@pytest.mark.parametrize("contenu", [b"", b"\x00\xff\xfe pas du csv \x00", b"colonne1,colonne2\n1,2\n", b"{pas du json", b'{"x": 1}', b"[1,2,3]"])
def test_fichiers_ruines_ne_plantent_pas(conn, ref, cfg, contenu):
    for nom in ("x.csv", "x.geojson"):
        r = importation.importer(conn, nom, contenu, cfg, ref)
        assert r["nb_acceptees"] == 0 and r["nb_refusees"] >= 1 and r["refusees"][0]["raison"]


def test_geojson_sans_photo_et_elements_casses(conn, bons_points, ref, cfg):
    p = bons_points[3]
    fc = {"type": "FeatureCollection", "features": [
        {"type": "Feature", "geometry": {"type": "Point", "coordinates": [p["lon"], p["lat"]]}, "properties": {"enqueteur": "E1", "secteur": p["secteur"]}},
        {"type": "Feature", "geometry": None, "properties": {}},
        {"type": "Feature", "geometry": {"type": "Polygon", "coordinates": []}, "properties": {}},
        {"type": "Feature", "geometry": {"type": "Point", "coordinates": ["x", "y"]}, "properties": {}},
        "pas un objet"]}
    r = importation.importer(conn, "d.geojson", json.dumps(fc).encode(), cfg, ref)
    assert r["nb_acceptees"] == 1 and r["nb_refusees"] == 4


def test_lignes_piegees_lisibles_sont_enregistrees_puis_rejetees(conn, bons_points, ref, cfg):
    lignes = "lat,lon\n0,0\n14,2\n99999,5\n"
    r = importation.importer(conn, "e.csv", lignes.encode(), cfg, ref)
    assert r["nb_acceptees"] == 3 and {a["statut"] for a in r["acceptees"]} == {"rejete"}
    assert len(base.lister_signalements(conn, "rejete")) == 3


def test_export_kobo_geopoint_et_colonnes_de_groupe(conn, bons_points, ref, cfg):
    """Export KoboToolbox : position dans « groupe/geopoint » (lat lon altitude précision), date de soumission, appareil."""
    p, q = bons_points[0], bons_points[1]
    contenu = ("start,end,deviceid,username,localisation/geopoint,_geolocation,_submission_time\n"
               f"2026-11-10T08:00:00.000+00:00,2026-11-10T08:05:00.000+00:00,imei-1,awa,{p['lat']} {p['lon']} 280.5 4.0,\"[{p['lat']}, {p['lon']}]\",2026-11-10T08:06:00\n"
               f"2026-11-10T09:00:00.000+00:00,2026-11-10T09:05:00.000+00:00,imei-1,awa,{q['lat']} {q['lon']} 281.0 5.0,\"[{q['lat']}, {q['lon']}]\",2026-11-10T09:06:00\n").encode()
    r = importation.importer(conn, "kobo.csv", contenu, cfg, ref)
    assert r["nb_acceptees"] == 2 and r["nb_refusees"] == 0, r
    ligne = base.lister_signalements(conn)[0]
    assert abs(ligne["lat"] - p["lat"]) < 1e-9 and abs(ligne["lon"] - p["lon"]) < 1e-9       # latitude d'abord, pas inversée
    assert ligne["appareil"] == "imei-1" and ligne["enqueteur"] == "awa" and ligne["horodatage"]


def test_export_odk_seulement_geolocation_et_virgule_decimale(conn, bons_points, ref, cfg):
    p = bons_points[2]
    contenu = (f"_geolocation;nature\n[{str(p['lat']).replace('.', ',')} {str(p['lon']).replace('.', ',')}];ordures\n").encode()
    r = importation.importer(conn, "odk.csv", contenu, cfg, ref)
    assert r["nb_acceptees"] == 1 and abs(base.lister_signalements(conn)[0]["lat"] - p["lat"]) < 1e-9


def test_export_kobo_position_vide_refusee_avec_explication(conn, bons_points, ref, cfg):
    p = bons_points[3]
    contenu = f"geopoint,_submission_time\n,2026-11-10T08:06:00\n{p['lat']} {p['lon']} 0 0,2026-11-10T08:07:00\n".encode()
    r = importation.importer(conn, "k.csv", contenu, cfg, ref)
    assert r["nb_acceptees"] == 1 and r["nb_refusees"] == 1 and "latitude" in r["refusees"][0]["raison"]


def test_csv_sans_aucune_colonne_de_position_reste_refuse(conn, ref, cfg):
    r = importation.importer(conn, "x.csv", b"nom,valeur\na,1\n", cfg, ref)
    assert r["nb_acceptees"] == 0 and "geopoint" in r["erreur_fichier"]


def test_csv_virgule_decimale_non_guillemetee_refuse_ligne_par_ligne(conn, bons_points, ref, cfg):
    p = bons_points[5]
    contenu = ("lat,lon,enqueteur\n12,35,-1,52,E1\n"                 # virgules décimales sans guillemets : trop de colonnes
               f"{p['lat']},{p['lon']},E2\n"                         # ligne correcte
               "douze,moins un,E3\n"                                 # coordonnées en texte
               '"12,35","-1,52",E4\n').encode()                      # entre guillemets : acceptée (puis rejetée : hors commune)
    r = importation.importer(conn, "v.csv", contenu, cfg, ref)
    assert r["nb_acceptees"] == 2 and r["nb_refusees"] == 2
    assert all("colonnes" in x["raison"] or "illisible" in x["raison"] for x in r["refusees"])
