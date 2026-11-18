"""Tests de la simulation multi-agents."""
import pytest

from oregdo.planning.scenario import Scenario
from oregdo.simulation.comparaison import comparer
from oregdo.simulation.modele import simuler

JOURS = 40


@pytest.fixture(scope="module")
def ref():
    return Scenario.depuis_config()


@pytest.fixture(scope="module")
def run_ref(ref):
    return simuler(ref, jours=JOURS)


def test_reproductible_par_graine(ref, run_ref):
    assert simuler(ref, jours=JOURS)["serie"] == run_ref["serie"]


def test_graine_differente_change_les_resultats(ref, run_ref):
    assert simuler(ref, jours=JOURS, graine=1)["serie"] != run_ref["serie"]


def test_bilan_masse_et_indicateurs(run_ref):
    f = run_ref["final"]
    assert len(run_ref["serie"]) == JOURS
    assert f["tonnes_collectees_totales"] + f["tonnes_fuite_totales"] <= f["tonnes_produites_totales"] * 1.05
    assert 0 <= f["taux_couverture_moyen"] <= 1
    assert f["budget_consomme_fcfa"] > 0 and f["recettes_abonnement_fcfa"] > 0
    assert all(s["depotoirs_actifs"] >= 0 for s in run_ref["serie"])


def test_brigade_deux_phases(run_ref):
    """Aucune sanction avant la fin de la phase de sensibilisation (config : 14 jours)."""
    from oregdo.config import charger_config
    delai = charger_config().simulation.brigade_laabal.phase_sensibilisation_jours
    avant = [s for s in run_ref["serie"] if s["jour"] <= delai]
    assert sum(s["sensibilisations"] for s in avant) > 0
    assert sum(s["sanctions"] for s in avant) == 0
    assert sum(s["sanctions"] for s in run_ref["serie"]) > 0 and run_ref["final"]["recettes_amendes_fcfa"] > 0


def test_camions_en_panne_reduisent_la_collecte(ref):
    ok = simuler(ref, jours=15)
    panne = simuler(ref.modifie(camions_nombre=2, voyages_max_par_jour=1), jours=15)
    assert panne["final"]["tonnes_collectees_totales"] < ok["final"]["tonnes_collectees_totales"]


def test_comparateur(ref):
    c = comparer(ref, ref.modifie(saison_pluies=True), jours=15)
    assert {i["indicateur"] for i in c["indicateurs"]} >= {"cout_par_tonne_fcfa", "taux_couverture_moyen"}
    couv = next(i for i in c["indicateurs"] if i["indicateur"] == "taux_couverture_moyen")
    assert couv["scenario"] <= couv["reference"]


def test_jours_invalides(ref):
    with pytest.raises(ValueError):
        simuler(ref, jours=0)
