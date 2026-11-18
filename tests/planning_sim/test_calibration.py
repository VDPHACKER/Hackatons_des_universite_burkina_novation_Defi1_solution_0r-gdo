"""Calibration sur le RGPH 2019 (docs/01) et sensibilité aux leviers : la référence doit être défendable."""
import pytest

from oregdo.planning import depotoirs
from oregdo.planning.plan import calculer_plan
from oregdo.planning.scenario import Scenario
from oregdo.simulation.modele import simuler

SYN = depotoirs.synthetiques(16, 1)   # indépendant de la base de l'application


@pytest.fixture(scope="module")
def sc():
    return Scenario.depuis_config()


@pytest.fixture(scope="module")
def ref(sc):
    return calculer_plan(sc, depotoirs=SYN)["kpi"]


def _kpi(s):
    return calculer_plan(s, depotoirs=SYN)["kpi"]


def test_reference_plan_conforme_au_rgph(ref):
    # RGPH 2019 : 43,7 % ramassage privé + 11,1 % bac = 54,8 % de collecte possible ; tas + rue = 33,3 % de fuite.
    assert 0.40 <= ref["taux_couverture_production"] <= 0.50
    assert 0.30 <= ref["taux_fuite"] <= 0.36
    assert ref["cout_investissement_pr_fcfa"] <= ref["budget_pr_fcfa"]


def test_reference_simulation_jour_1_conforme_au_rgph(sc):
    j1 = simuler(sc, jours=1)["serie"][0]
    assert 0.38 <= j1["taux_couverture"] <= 0.50
    assert 0.30 <= j1["tonnes_fuite_depotoirs"] / j1["tonnes_produites"] <= 0.37


def test_pluie_baisse_la_couverture_et_hausse_le_cout(sc, ref):
    k = _kpi(sc.modifie(saison_pluies=True))
    assert k["taux_couverture_production"] < ref["taux_couverture_production"]
    assert k["cout_par_tonne_fcfa"] > ref["cout_par_tonne_fcfa"]


def test_panne_hausse_la_fuite(sc, ref):
    k = _kpi(sc.modifie(camions_en_panne=list(range(12))))
    assert k["taux_fuite"] > ref["taux_fuite"]
    assert k["taux_couverture_production"] < ref["taux_couverture_production"]


def test_plus_de_budget_plus_de_couverture(sc, ref):
    assert _kpi(sc.modifie(budget_pr_fcfa=sc.budget_pr_fcfa * 1.4))["couverture_pr"] > ref["couverture_pr"]
    assert _kpi(sc.modifie(budget_pr_fcfa=sc.budget_pr_fcfa / 2))["couverture_pr"] < ref["couverture_pr"]


def test_moins_de_camions_moins_de_couverture(sc, ref):
    assert _kpi(sc.modifie(camions_nombre=20))["taux_couverture_production"] < ref["taux_couverture_production"]


def test_simulation_panne_plus_de_fuite_cumulee(sc):
    a = simuler(sc, jours=10)["final"]["tonnes_fuite_totales"]
    b = simuler(sc.modifie(camions_en_panne=list(range(15))), jours=10)["final"]["tonnes_fuite_totales"]
    assert b > a
