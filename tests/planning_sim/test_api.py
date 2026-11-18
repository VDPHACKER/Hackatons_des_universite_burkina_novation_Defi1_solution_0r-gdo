import os
"""Tests de l'API (TestClient, seulement notre routeur)."""
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


def test_scenario_lecture_et_modification():
    s = client.get("/api/scenario").json()
    assert s["scenario"]["camions_nombre"] == s["reference"]["camions_nombre"]
    r = client.put("/api/scenario", json={"camions_nombre": 12, "budget_pr_fcfa": 30000000})
    assert r.status_code == 200 and r.json()["scenario"]["camions_nombre"] == 12


def test_scenario_invalide_en_francais():
    r = client.put("/api/scenario", json={"taux_abonnement": 3})
    assert r.status_code == 422 and "abonnement" in r.json()["detail"]
    assert client.put("/api/scenario", json={"inconnu": 1}).status_code == 422


def test_plan_geojson_et_recalcul_chronometre():
    client.post("/api/plan/recalculer")             # chauffe : distances du graphe routier gardées en mémoire, comme au démarrage du serveur
    r = client.post("/api/plan/recalculer").json()
    assert r["pr"]["type"] == "FeatureCollection" and r["tournees"]["type"] == "FeatureCollection"
    # Objectif : quelques secondes sur un PC de mairie (mesuré : 1,2 à 2 s). Le seuil du test laisse de la marge pour un
    # ordinateur plus lent ou chargé ; OREGDO_SEUIL_RECALCUL_S permet de le resserrer.
    seuil = float(os.environ.get("OREGDO_SEUIL_RECALCUL_S", "15"))
    print(f"recalcul du plan : {r['temps_calcul_s']:.2f} s (seuil {seuil} s)")
    assert r["temps_calcul_s"] < seuil and "recalculé" in r["message"]
    assert client.get("/api/plan").json()["empreinte"] == r["empreinte"]


def test_alea_panne_et_pluie():
    p = client.post("/api/alea", json={"type": "panne_camion", "params": {"camions": [0, 1]}}).json()
    assert p["plan"]["kpi"]["camions_disponibles"] == p["plan"]["scenario"]["camions_nombre"] - 2
    assert all(f["properties"]["camion"] not in (0, 1) for f in p["plan"]["tournees"]["features"])
    q = client.post("/api/alea", json={"type": "saison_pluies"}).json()
    assert q["plan"]["scenario"]["saison_pluies"] is True


def test_alea_signalements_pieges_plan_inchange():
    client.post("/api/plan/recalculer")
    r = client.post("/api/alea", json={"type": "signalements_pieges", "params": {"nombre": 30}}).json()
    assert r["plan_modifie"] is False and "vérifiés" in r["message"]


def test_alea_inconnu():
    r = client.post("/api/alea", json={"type": "meteorite"})
    assert r.status_code == 422 and "Aléa inconnu" in r.json()["detail"]


def test_simulation_et_comparaison():
    r = client.post("/api/simulation/run", json={"jours": 10}).json()
    assert len(r["serie"]) == 10
    client.post("/api/alea", json={"type": "saison_pluies"})
    c = client.get("/api/simulation/comparaison", params={"jours": 10}).json()
    assert c["indicateurs"] and len(c["scenario"]["serie"]) == 10
    assert client.post("/api/simulation/run", json={"jours": 0}).status_code == 422


def test_suggestions():
    r = client.get("/api/suggestions/emplacements", params={"n": 3}).json()
    assert 0 < len(r["features"]) <= 3 and "justification" in r["features"][0]["properties"]
    assert client.get("/api/suggestions/emplacements", params={"n": 0}).status_code == 422
