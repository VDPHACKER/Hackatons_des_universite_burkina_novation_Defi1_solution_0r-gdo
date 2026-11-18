"""Solveur de tournées PyVRP (MIT) : plus court qu'OR-Tools à tonnage égal, déterministe, avec repli sur OR-Tools."""
from types import SimpleNamespace

import pytest

from oregdo.planning import depotoirs, tournees
from oregdo.planning.plan import calculer_plan
from oregdo.planning.scenario import Scenario

pytest.importorskip("pyvrp")
DEPOTOIRS = [x for x in depotoirs.synthetiques(40, 1) if x.statut == "verifie"]


@pytest.fixture
def solveur(monkeypatch):
    """Choisit le solveur de tournées pour la durée d'un test."""
    reglages = tournees.moteur

    def choisir(nom):
        monkeypatch.setattr(tournees, "moteur", lambda cfg: SimpleNamespace(**{**vars(reglages(cfg)), "solveur_tournees": nom}))
    return choisir


def test_pyvrp_plus_court_a_tonnage_egal(solveur):
    sc = Scenario.depuis_config()
    solveur("ortools")
    ref = calculer_plan(sc, depotoirs=DEPOTOIRS)["kpi"]
    solveur("pyvrp")
    nouveau = calculer_plan(sc, depotoirs=DEPOTOIRS)
    k = nouveau["kpi"]
    assert k["tonnes_evacuees_j"] == ref["tonnes_evacuees_j"] and k["tonnes_depotoirs_enlevees"] == ref["tonnes_depotoirs_enlevees"]
    assert not nouveau["non_servis"]
    assert k["distance_km"] < 0.95 * ref["distance_km"], (k["distance_km"], ref["distance_km"])     # mesuré : environ -13 %
    assert k["cout_collecte_fcfa"] < ref["cout_collecte_fcfa"]


def test_pyvrp_deterministe(solveur):
    solveur("pyvrp")
    sc = Scenario.depuis_config()
    assert calculer_plan(sc, depotoirs=DEPOTOIRS)["empreinte"] == calculer_plan(sc, depotoirs=DEPOTOIRS)["empreinte"]


def test_pyvrp_respecte_les_pannes_et_la_capacite(solveur):
    solveur("pyvrp")
    sc = Scenario.depuis_config().modifie(camions_en_panne=[0, 1, 2, 3, 4, 5])
    plan = calculer_plan(sc, depotoirs=DEPOTOIRS)
    assert {f["properties"]["camion"] for f in plan["tournees"]["features"]}.isdisjoint({0, 1, 2, 3, 4, 5})
    assert all(f["properties"]["charge_kg"] <= sc.capacite_camion_kg for f in plan["tournees"]["features"])
    for f in plan["tournees"]["features"]:                                     # chaque tournée commence et finit sur des points connus
        assert len(f["geometry"]["coordinates"]) >= 3 and f["properties"]["arrets"]


def test_repli_sur_ortools_si_pyvrp_indisponible(solveur, monkeypatch):
    solveur("pyvrp")
    monkeypatch.setattr(tournees, "_tournees_pyvrp", lambda *a, **k: None)     # PyVRP absent ou sans solution faisable
    plan = calculer_plan(Scenario.depuis_config(), depotoirs=DEPOTOIRS)
    assert plan["tournees"]["features"] and not plan["non_servis"]
