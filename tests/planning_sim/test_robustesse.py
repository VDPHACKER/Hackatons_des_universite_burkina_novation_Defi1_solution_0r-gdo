"""Robustesse : toute entrée absurde donne 422 (jamais 500, jamais un calcul démesuré) avec un message en français."""
import json
import time

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from oregdo.api import plan as api
from oregdo.simulation import comparaison as cmp

app = FastAPI()
app.include_router(api.router, prefix="/api")
client = TestClient(app, raise_server_exceptions=False)   # un 500 doit apparaître comme un 500, pas comme une exception

class Client:
    """Envoie le JSON tel quel (json.dumps accepte NaN et Infinity, comme un client malveillant)."""

    def __init__(self, c):
        self.c = c

    def get(self, *a, **k):
        return self.c.get(*a, **k)

    def _envoi(self, methode, url, json_=None):
        return self.c.request(methode, url, content=json.dumps(json_), headers={"content-type": "application/json"})

    def put(self, url, json=None):
        return self._envoi("PUT", url, json)

    def post(self, url, json=None):
        return self._envoi("POST", url, json)


client = Client(client)
NAN, INF = float("nan"), float("inf")
CARRE = {"type": "Polygon", "coordinates": [[[-1.60, 12.30], [-1.585, 12.30], [-1.585, 12.315], [-1.60, 12.315], [-1.60, 12.30]]]}


@pytest.fixture(autouse=True)
def remise_a_zero():
    api.reinitialiser()


def _refus(reponse, mot=None):
    assert reponse.status_code == 422, (reponse.status_code, reponse.text[:200])
    detail = reponse.json()["detail"]
    assert isinstance(detail, str) and detail
    if mot:
        assert mot in detail, detail


SCENARIO_ABSURDE = [
    {"camions_nombre": 1e9}, {"camions_nombre": 5000}, {"camions_nombre": -1}, {"camions_nombre": "abc"},
    {"camions_nombre": None}, {"camions_nombre": NAN}, {"camions_nombre": INF}, {"camions_nombre": True},
    {"camions_nombre": 40.5}, {"facteur_population": 0}, {"facteur_population": 11}, {"facteur_population": NAN},
    {"taux_abonnement": 1.5}, {"taux_abonnement": -0.1}, {"budget_pr_fcfa": 1e15}, {"budget_pr_fcfa": -5},
    {"rayon_acces_pr_m": 10}, {"rayon_acces_pr_m": 1e6}, {"frequence_collecte_jours": 0}, {"frequence_collecte_jours": 31},
    {"voyages_max_par_jour": 11}, {"voyages_max_par_jour": 0}, {"capacite_camion_kg": 100}, {"capacite_camion_kg": 1e9},
    {"camions_en_panne": [-1]}, {"camions_en_panne": [0, 0]}, {"camions_en_panne": [999]}, {"camions_en_panne": "x"},
    {"camions_en_panne": [NAN]}, {"saison_pluies": "oui"}, {"saison_pluies": None}, {"inconnu": 1},
    {"nouveaux_quartiers": "x"}, {"nouveaux_quartiers": [{"population": None, "polygone": CARRE}]},
]


@pytest.mark.parametrize("corps", SCENARIO_ABSURDE, ids=lambda c: str(c)[:40])
def test_put_scenario_absurde_donne_422(corps):
    t = time.perf_counter()
    _refus(client.put("/api/scenario", json=corps))
    assert time.perf_counter() - t < 1.0
    assert client.get("/api/scenario").json()["scenario"]["camions_nombre"] == 40      # rien n'a été mémorisé


def test_put_scenario_corps_non_objet():
    assert client.put("/api/scenario", json=[1, 2]).status_code == 422


def test_panne_plus_grande_que_la_flotte_apres_reduction():
    _refus(client.put("/api/scenario", json={"camions_nombre": 5, "camions_en_panne": [10]}))


@pytest.mark.parametrize("jours", [1e7, 366, 0, -5, "10", NAN, INF, 1.5, True, [1]], ids=str)
def test_simulation_jours_absurdes(jours):
    t = time.perf_counter()
    _refus(client.post("/api/simulation/run", json={"jours": jours}))
    assert time.perf_counter() - t < 2.0


def test_simulation_corps_invalide():
    _refus(client.post("/api/simulation/run", json={"jours": 5, "scenario": {"camions_nombre": 1e9}}))
    _refus(client.post("/api/simulation/run", json={"jours": 5, "scenario": [1]}))


ALEAS_ABSURDES = [
    {"type": "panne_camion", "params": {"nombre": -3}}, {"type": "panne_camion", "params": {"camions": -2}},
    {"type": "panne_camion", "params": {"camions": [-1]}}, {"type": "panne_camion", "params": {"camions": [1, 1]}},
    {"type": "panne_camion", "params": {"camions": [500]}}, {"type": "panne_camion", "params": {"nombre": 1000}},
    {"type": "panne_camion", "params": {"nombre": "abc"}}, {"type": "panne_camion", "params": {"nombre": NAN}},
    {"type": "panne_camion", "params": [1]}, {"type": "saison_pluies", "params": {"actif": "oui"}},
    {"type": "nouveau_quartier", "params": {"population": None, "polygone": CARRE}},
    {"type": "nouveau_quartier", "params": {"polygone": CARRE}},
    {"type": "nouveau_quartier", "params": {"population": 0, "polygone": CARRE}},
    {"type": "nouveau_quartier", "params": {"population": -5, "polygone": CARRE}},
    {"type": "nouveau_quartier", "params": {"population": NAN, "polygone": CARRE}},
    {"type": "nouveau_quartier", "params": {"population": 1e12, "polygone": CARRE}},
    {"type": "nouveau_quartier", "params": {"population": "beaucoup", "polygone": CARRE}},
    {"type": "nouveau_quartier", "params": {"population": 1000}},
    {"type": "nouveau_quartier", "params": {"population": 1000, "polygone": {"type": "Point", "coordinates": [0, 0]}}},
    {"type": "nouveau_quartier", "params": {"population": 1000, "polygone": "x"}},
    {"type": "nouveau_quartier", "params": {"population": 1000, "polygone": {"type": "Polygon", "coordinates": [[[0, 0], [1, 1]]]}}},
    {"type": "nouveau_quartier", "params": {"population": 1000, "polygone": {"type": "Polygon", "coordinates": [[["a", "b"]] * 4]}}},
    # figure en papillon (auto-intersection)
    {"type": "nouveau_quartier", "params": {"population": 1000, "polygone": {"type": "Polygon", "coordinates": [[
        [-1.60, 12.30], [-1.59, 12.31], [-1.59, 12.30], [-1.60, 12.31], [-1.60, 12.30]]]}}},
    # trop de points
    {"type": "nouveau_quartier", "params": {"population": 1000, "polygone": {"type": "Polygon", "coordinates": [
        [[-1.6 + i * 1e-6, 12.3] for i in range(600)] + [[-1.5, 12.4], [-1.6, 12.3]]]}}},
    # surface énorme (toute la commune x 10)
    {"type": "nouveau_quartier", "params": {"population": 1000, "polygone": {"type": "Polygon", "coordinates": [[
        [-2.5, 11.5], [-0.5, 11.5], [-0.5, 13.5], [-2.5, 13.5], [-2.5, 11.5]]]}}},
    # très loin de la commune
    {"type": "nouveau_quartier", "params": {"population": 1000, "polygone": {"type": "Polygon", "coordinates": [[
        [2.30, 48.80], [2.31, 48.80], [2.31, 48.81], [2.30, 48.81], [2.30, 48.80]]]}}},
    {"type": "signalements_pieges", "params": {"nombre": 10**6}}, {"type": "signalements_pieges", "params": {"nombre": -1}},
    {"type": "signalements_pieges", "params": {"signalements": "x"}},
    {"type": 5}, {"params": {}}, {"type": "meteorite"},
]


@pytest.mark.parametrize("corps", ALEAS_ABSURDES, ids=lambda c: str(c)[:60])
def test_alea_absurde_donne_422_et_ne_change_rien(corps):
    avant = client.get("/api/scenario").json()["scenario"]
    t = time.perf_counter()
    _refus(client.post("/api/alea", json=corps))
    assert time.perf_counter() - t < 3.0
    assert client.get("/api/scenario").json()["scenario"] == avant


def test_alea_corps_non_objet():
    assert client.post("/api/alea", json=[1]).status_code == 422


def test_quartier_proche_de_la_commune_avertit():
    """Un quartier valide en bordure est accepté ; l'éventuel avertissement figure dans le message."""
    r = client.post("/api/alea", json={"type": "nouveau_quartier", "params": {"population": 20000, "polygone": CARRE}})
    assert r.status_code == 200 and "ajouté" in r.json()["message"]


@pytest.mark.parametrize("valeur", ["abc", "nan", "inf", "-3", "0", "1.5"])
def test_parametres_d_url_absurdes(valeur):
    _refus(client.get("/api/simulation/comparaison", params={"jours": valeur}))
    _refus(client.get("/api/suggestions/emplacements", params={"n": valeur}))


def test_flotte_maximale_reste_rapide():
    """Les bornes maximales acceptées ne doivent pas faire exploser le calcul (avant : 8 Go et plus de 40 s)."""
    sc = client.put("/api/scenario", json={"camions_nombre": 500, "voyages_max_par_jour": 10})
    assert sc.status_code == 200
    t = time.perf_counter()
    r = client.post("/api/plan/recalculer")
    duree = time.perf_counter() - t
    print("flotte 500 x 10 voyages :", round(duree, 2), "s")
    assert r.status_code == 200 and duree < 10


def test_simulation_365_jours_dans_le_garde_fou():
    t = time.perf_counter()
    r = client.post("/api/simulation/run", json={"jours": 365})
    duree = time.perf_counter() - t
    print("simulation 365 jours :", round(duree, 2), "s", r.status_code)
    assert r.status_code in (200, 422) and duree < 60
    if r.status_code == 422:
        assert "durée maximale" in r.json()["detail"]


def test_comparaison_en_cache():
    cmp.vider_cache()
    t = time.perf_counter()
    a = client.get("/api/simulation/comparaison", params={"jours": 10})
    froid = time.perf_counter() - t
    t = time.perf_counter()
    b = client.get("/api/simulation/comparaison", params={"jours": 10})
    chaud = time.perf_counter() - t
    print("comparaison à froid", round(froid, 2), "s ; à chaud", round(chaud, 2), "s")
    assert a.status_code == b.status_code == 200 and a.json() == b.json()
    assert chaud < 2.0 and chaud < froid
    # Un scénario différent n'utilise pas le résultat mémorisé.
    client.put("/api/scenario", json={"camions_nombre": 30})
    c = client.get("/api/simulation/comparaison", params={"jours": 10}).json()
    assert c["scenario"]["diagnostic"]["camions_actuels"] == 30


def test_cache_invalide_si_la_base_change(tmp_path, monkeypatch):
    from oregdo.planning import depotoirs
    cmp.vider_cache()
    s1 = cmp._signature_sources()
    base = tmp_path / "oregdo.db"
    base.write_bytes(b"x")
    monkeypatch.setattr(depotoirs, "CHEMIN_BASE", base)
    assert cmp._signature_sources() != s1
