"""Plan de gestion d'un arrondissement : le découpage doit retomber sur les totaux de la commune et rester honnête."""
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from oregdo.api import plan as api

app = FastAPI()
app.include_router(api.router, prefix="/api")
client = TestClient(app)


@pytest.fixture(autouse=True)
def remise_a_zero():
    api.reinitialiser()


def test_les_douze_arrondissements_retombent_sur_la_commune():
    kpi = client.get("/api/plan").json()["kpi"]
    t = client.get("/api/plan/arrondissements").json()
    assert t["synthetique"] is True and "synthétique" in t["avertissement"]          # le découpage est dit synthétique
    lignes = t["arrondissements"]
    assert len(lignes) == 12
    assert sum(x["nb_pr"] for x in lignes) == kpi["nb_pr"]
    assert sum(x["nb_depotoirs_verifies"] for x in lignes) == kpi["nb_depotoirs_verifies"]
    assert sum(x["tonnes_produites_j"] for x in lignes) == pytest.approx(kpi["tonnes_produites_j"], abs=1.0)
    assert sum(x["population"] for x in lignes) == pytest.approx(client.get("/api/scenario").json()["scenario"]["facteur_population"] * 2415266, rel=0.001)
    couvertures = [x["couverture_population"] for x in lignes]
    assert couvertures == sorted(couvertures)                                        # du moins bien au mieux desservi
    assert all(0 <= c <= 1 for c in couvertures)


def test_plan_d_un_arrondissement():
    r = client.get("/api/plan/arrondissement/a06")                                   # insensible à la casse
    assert r.status_code == 200
    p = r.json()
    a = p["arrondissement"]
    assert a["code"] == "A06" and a["nom"] == "Arrondissement 6" and a["population"] > 0
    assert len(p["pr"]["features"]) == a["nb_pr"] and len(p["depotoirs"]["features"]) == a["nb_depotoirs_verifies"]
    assert len(p["tournees"]["features"]) == a["nb_voyages"]
    assert p["contour"]["geometry"]["type"] in ("Polygon", "MultiPolygon") and 1 <= a["rang_couverture"] <= 12
    assert p["synthetique"] is True


def test_arrondissement_inconnu_refuse_en_francais():
    r = client.get("/api/plan/arrondissement/A99")
    assert r.status_code == 404 and "inconnu" in r.json()["detail"]


def test_le_plan_d_arrondissement_suit_le_scenario():
    avant = client.get("/api/plan/arrondissement/A06").json()["arrondissement"]
    assert client.put("/api/scenario", json={"taux_tri": 0.6}).status_code == 200
    apres = client.get("/api/plan/arrondissement/A06").json()["arrondissement"]       # le plan est recalculé après un changement de paramètre
    assert avant["tonnes_valorisees_j"] == 0 and apres["tonnes_valorisees_j"] > 0
    assert apres["tonnes_a_collecter_j"] < avant["tonnes_a_collecter_j"]
