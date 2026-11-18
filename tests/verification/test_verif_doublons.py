"""Tests du regroupement en dépotoirs, de la confiance et de l'export OSM."""
import xml.etree.ElementTree as ET

import pytest

from oregdo.verification import base, doublons, score as s
from outils_photo import photo_neuve


@pytest.fixture
def conn(tmp_path):
    return base.ouvrir(tmp_path / "t.db")


def poster(conn, sig, ref, cfg):
    return s.verifier_et_enregistrer(conn, sig, [photo_neuve()], ref, cfg)


def test_dbscan_regroupe_a_moins_de_rayon():
    pts = [(12.35, -1.52), (12.35005, -1.52), (12.36, -1.52)]   # 5 m d'écart puis ~1,1 km
    e = doublons.regrouper(pts, 40)
    assert e[0] == e[1] != e[2]


def test_dix_signalements_du_meme_enqueteur_font_un_depotoir_sans_gonfler(conn, sig, ref, cfg):
    from datetime import datetime, timedelta, timezone
    for i in range(10):
        # même enquêteur, jours différents : un seul est « nouveau », les autres sont des répétitions (grave)
        h = (datetime.now(timezone.utc) - timedelta(days=i + 1)).isoformat()
        poster(conn, {**sig, "horodatage": h, "appareil": f"A{i}"}, ref, cfg)
    assert doublons.consolider(conn, cfg) == 1
    d = conn.execute("SELECT * FROM depotoir").fetchone()
    assert d["nb_enqueteurs"] == 1 and d["nb_signalements"] == 1


def test_la_confiance_monte_avec_les_enqueteurs_distincts(conn, sig, ref, cfg):
    poster(conn, sig, ref, cfg)
    doublons.consolider(conn, cfg)
    c1 = conn.execute("SELECT confiance FROM depotoir").fetchone()[0]
    from datetime import datetime, timedelta, timezone
    for i in (2, 3):     # à des heures différentes : trois signalements simultanés seraient une rafale coordonnée
        h = (datetime.now(timezone.utc) - timedelta(hours=1 + 3 * i)).isoformat()
        poster(conn, {**sig, "enqueteur": f"E{i}", "appareil": f"A{i}", "horodatage": h}, ref, cfg)
    assert doublons.consolider(conn, cfg) == 1
    d = conn.execute("SELECT * FROM depotoir").fetchone()
    assert d["nb_enqueteurs"] == 3 and d["nb_signalements"] == 3 and d["confiance"] >= c1


def test_gonflage_ne_cree_pas_de_confirmation(conn, sig, ref, cfg):
    for _ in range(5):
        poster(conn, sig, ref, cfg)           # même appareil, même seconde
    doublons.consolider(conn, cfg)
    d = conn.execute("SELECT * FROM depotoir").fetchone()
    assert d["nb_signalements"] == 1 and d["nb_enqueteurs"] == 1
    assert len(base.lister_signalements(conn, "rejete")) == 4     # conservés, pas supprimés


def test_revalidation_manuelle_met_a_jour_le_depotoir(conn, bons_points, ref, cfg, sig):
    # un signalement « à confirmer » devient dépotoir une fois validé à la main
    r = poster(conn, {**sig, "secteur": "n'existe pas", "horodatage": None}, ref, cfg)
    base.revalider(conn, r["id"], "verifie", "Awa", "Vu sur place")
    assert doublons.consolider(conn, cfg) == 1
    base.revalider(conn, r["id"], "rejete", "Awa", "Finalement déblayé")
    assert doublons.consolider(conn, cfg) == 0
    assert conn.execute("SELECT statut FROM depotoir").fetchone()[0] == "sans_signalement_valide"


def test_export_osm_uniquement_verifies(conn, sig, bons_points, ref, cfg):
    poster(conn, sig, ref, cfg)
    poster(conn, {**bons_points[9], "lat": 0, "lon": 0}, ref, cfg)    # rejeté
    doublons.consolider(conn, cfg)
    exp = doublons.export_osm(conn, cfg)
    assert exp["nombre"] == 1 and len(exp["geojson"]["features"]) == 1
    noeud = ET.fromstring(exp["osm"].split("?>\n", 1)[1]).find("node")
    tags = {t.get("k"): t.get("v") for t in noeud.findall("tag")}
    assert tags["landuse"] == "landfill" and tags["source"] == "Orẽgdo"
