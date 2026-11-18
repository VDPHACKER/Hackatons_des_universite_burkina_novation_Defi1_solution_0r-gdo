"""Test d'intégration de l'API (routeur monté seul, base temporaire)."""
import base64
from datetime import datetime, timedelta, timezone

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from oregdo.api import signalements
from outils_photo import jpeg


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setenv("OREGDO_DB", str(tmp_path / "api.db"))
    app = FastAPI()
    app.include_router(signalements.router, prefix="/api")
    return TestClient(app)


def corps(sig, **kw):
    return {k: sig[k] for k in ("lat", "lon", "secteur", "enqueteur", "appareil", "horodatage")} | kw


def test_parcours_complet(client, sig, bons_points):
    r = client.post("/api/signalements", json=corps(sig, photos=[base64.b64encode(jpeg(1)).decode()]))
    assert r.status_code == 201 and r.json()["statut"] == "verifie" and "vérifié" in r.json()["message"]
    # gonflage : même appareil, même instant
    assert client.post("/api/signalements", json=corps(sig)).json()["statut"] == "rejete"
    # hors commune et (0,0) et valeurs absurdes : rejetés, pas d'erreur serveur
    for piege in ({"lat": 0, "lon": 0}, {"lat": 14, "lon": 2}, {"lat": -1.5, "lon": 12.3}):
        rr = client.post("/api/signalements", json=corps(sig, **piege) | {"appareil": "Z" + str(piege["lat"])})
        assert rr.status_code == 201 and rr.json()["statut"] == "rejete"
    liste = client.get("/api/signalements").json()
    assert liste["nombre"] == 5
    assert client.get("/api/signalements?statut=rejete").json()["nombre"] == 4
    assert client.get("/api/signalements?statut=bidon").status_code == 400
    stats = client.get("/api/signalements/stats").json()
    assert stats["par_statut"]["verifie"] == 1 and stats["par_motif_rejet"]["position"] >= 3 and stats["nb_essais_masques"] == 0
    assert stats["nb_depotoirs"] == 1


def test_revalidation_et_depotoirs_et_export(client, sig):
    r = client.post("/api/signalements", json=corps(sig, secteur=None, horodatage=None, photos=["pas-du-base64!"])).json()
    ancien = r["statut"]
    rep = client.post(f"/api/signalements/{r['id']}/revalider", json={"statut": "verifie", "agent": "Awa", "motif": "Vu sur place"})
    assert rep.status_code == 200 and rep.json()["journal"][-1]["agent"] == "test"   # l'agent est le compte connecté, pas le corps de la requête
    assert rep.json()["journal"][-1]["ancien_statut"] == ancien
    assert client.post("/api/signalements/999/revalider", json={"statut": "verifie", "agent": "A", "motif": "m"}).status_code == 404
    assert client.post(f"/api/signalements/{r['id']}/revalider", json={"statut": "zzz", "agent": "A", "motif": "m"}).status_code == 400
    dep = client.get("/api/depotoirs").json()
    assert len(dep["features"]) == 1 and dep["features"][0]["properties"]["confiance"] > 0
    exp = client.get("/api/export/osm").json()
    assert exp["nombre"] == 1 and "<osm" in exp["osm"]
    assert client.get("/api/export/osm?format=osm").headers["content-type"].startswith("application/xml")
    assert client.get("/api/export/osm?format=geojson").json()["type"] == "FeatureCollection"


def test_import_fichier_mal_forme(client, bons_points):
    p = bons_points[4]
    contenu = f"lat,lon,secteur\n{p['lat']},{p['lon']},{p['secteur']}\nx,y\n".encode()
    r = client.post("/api/signalements/import", files={"fichier": ("a.csv", contenu, "text/csv")})
    assert r.status_code == 200 and r.json()["nb_acceptees"] == 1 and r.json()["nb_refusees"] == 1
    r = client.post("/api/signalements/import", files={"fichier": ("b.geojson", b"{cass", "application/json")})
    assert r.status_code == 200 and r.json()["erreur_fichier"]


@pytest.mark.parametrize("nature,caniveau", [(["plastique", "organique"], "oui"), ("gravats", "non"), (["gravats"], "true"),
                                              (None, 1), ("mixte", 0), ([], False), ("x", "peut-être"), ("x", True)])
def test_formes_tolerantes_nature_et_caniveau(client, sig, nature, caniveau):
    r = client.post("/api/signalements", json=corps(sig, nature=nature, caniveau=caniveau, accessible="camion",
                                                    precision_m=12, sans_photo=True, exif={"a": 1}))
    assert r.status_code == 201, r.text
    s = client.get("/api/signalements").json()["signalements"][-1]
    if isinstance(nature, list) and nature:
        assert s["nature"] == ", ".join(nature)
    assert s["caniveau"] in (None, 0, 1)
    assert s["accessibilite"] == "camion"


def test_date_client_et_photos_en_objet(client, sig):
    c = corps(sig); c.pop("horodatage")
    r = client.post("/api/signalements", json=c | {"date_client": sig["horodatage"], "photos": [{"data": base64.b64encode(jpeg(77)).decode()}]})
    assert r.status_code == 201 and r.json()["statut"] == "verifie"


@pytest.mark.parametrize("lat,lon,motif_attendu", [(0, 0, "(0, 0)"), (48.85, 2.35, "en dehors de la commune")])
def test_revalidation_humaine_ne_valide_pas_un_lieu_impossible(client, sig, lat, lon, motif_attendu):
    """Défaut relevé par le jury technique : un agent muni du jeton pouvait faire entrer un point (0,0) dans le plan."""
    r = client.post("/api/signalements", json=corps(sig, lat=lat, lon=lon, secteur="S01")).json()
    assert r["statut"] == "rejete"
    for cible in ("verifie", "a_confirmer"):
        rep = client.post(f"/api/signalements/{r['id']}/revalider", json={"statut": cible, "agent": "Awa", "motif": "essai"})
        assert rep.status_code == 409
        assert motif_attendu in rep.json()["detail"]
    # Le point impossible n'entre ni dans les dépotoirs ni dans les signalements vérifiés
    assert client.get("/api/depotoirs").json()["features"] == []
    assert client.get("/api/signalements?statut=verifie").json()["nombre"] == 0
    # Rejeter reste toujours permis
    assert client.post(f"/api/signalements/{r['id']}/revalider", json={"statut": "rejete", "agent": "Awa", "motif": "confirmé"}).status_code == 200


def test_revalidation_humaine_reste_possible_pour_un_lieu_valide(client, sig):
    r = client.post("/api/signalements", json=corps(sig)).json()
    rep = client.post(f"/api/signalements/{r['id']}/revalider", json={"statut": "verifie", "agent": "Awa", "motif": "Vu sur place"})
    assert rep.status_code == 200 and rep.json()["signalement"]["statut"] == "verifie"
