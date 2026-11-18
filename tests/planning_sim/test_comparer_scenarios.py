"""Tableau de bord : comparaison de plusieurs scénarios côte à côte et description de la commune servie."""
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


def test_la_commune_servie_est_decrite_pour_l_interface():
    c = client.get("/api/commune").json()
    assert c["code"] == "ouaga" and c["nom"] == "Ouagadougou" and c["marque"] == "Orẽgdo"
    assert c["population"] == 2415266 and len(c["centre"]) == 2 and len(c["bbox"]) == 4
    assert c["pack"].endswith("/") and c["fond"].endswith("/fond/")


def test_comparer_calcule_chaque_scenario_sans_toucher_au_scenario_courant():
    avant = client.get("/api/scenario").json()["scenario"]
    r = client.post("/api/plan/comparer", json={"scenarios": [{}, {"camions_nombre": 60}, {"camions_nombre": 25, "frequence_collecte_jours": 2}]})
    assert r.status_code == 200
    s = r.json()["scenarios"]
    assert [x["numero"] for x in s] == [1, 2, 3] and r.json()["temps_total_s"] > 0
    for x in s:
        k = x["kpi"]
        assert {"tonnes_evacuees_j", "tonnes_fuite_j", "taux_couverture_production", "cout_par_tonne_fcfa", "camions_utilises"} <= set(k)
        assert 0 <= k["taux_couverture_production"] <= 1
    assert s[1]["kpi"]["camions_disponibles"] == 60 and s[0]["kpi"]["camions_disponibles"] == avant["camions_nombre"]
    assert s[2]["kpi"]["taux_couverture_production"] < s[0]["kpi"]["taux_couverture_production"]     # moins de camions et un passage sur deux : moins évacué
    assert client.get("/api/scenario").json()["scenario"] == avant                                       # l'état courant n'a pas bougé


def test_recharger_la_configuration_remet_le_scenario_aux_valeurs_du_fichier():
    client.put("/api/scenario", json={"camions_nombre": 7})
    assert client.get("/api/scenario").json()["scenario"]["camions_nombre"] == 7
    r = client.post("/api/config/recharger")
    assert r.status_code == 200 and "Paramètres relus" in r.json()["message"]
    ref = client.get("/api/scenario").json()
    assert ref["scenario"]["camions_nombre"] == ref["reference"]["camions_nombre"] != 7


def test_un_fichier_invalide_est_refuse_et_l_ancienne_configuration_est_conservee(monkeypatch):
    from oregdo.config import charger_config
    avant = charger_config.cache_info().currsize
    monkeypatch.setattr("oregdo.config.yaml.safe_load", lambda *_a, **_k: (_ for _ in ()).throw(ValueError("YAML cassé")))
    r = client.post("/api/config/recharger")
    assert r.status_code == 422 and "ancien est conservé" in r.json()["detail"]
    assert charger_config.cache_info().currsize == avant                          # le cache n'a pas été vidé
    monkeypatch.undo()
    assert client.get("/api/scenario").status_code == 200


@pytest.mark.parametrize("corps", [
    {}, {"scenarios": []}, {"scenarios": [{}] * 5}, {"scenarios": "non"}, {"scenarios": [{"inconnu": 1}]},
    {"scenarios": [{"camions_nombre": -3}]}, {"scenarios": [{"taux_abonnement": 7}]}, {"scenarios": ["pas un objet"]},
])
def test_comparer_refuse_les_entrees_invalides_en_francais(corps):
    r = client.post("/api/plan/comparer", json=corps)
    assert r.status_code == 422 and isinstance(r.json()["detail"], str)
