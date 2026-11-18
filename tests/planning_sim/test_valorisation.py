"""Levier « valorisation » : des ménages trient et revendent leurs recyclables (hypothèses [H] de la configuration)."""
import pytest

from oregdo.config import charger_config
from oregdo.planning import valorisation
from oregdo.planning.plan import calculer_plan
from oregdo.planning.scenario import Scenario
from oregdo.simulation.modele import simuler


def plan(tri):
    sc = Scenario.depuis_config().modifie(taux_tri=tri)
    sc.valider()
    return calculer_plan(sc)["kpi"]


@pytest.fixture(scope="module")
def kpis():
    return {t: plan(t) for t in (0.0, 0.3, 0.6)}


def test_sans_tri_le_moteur_est_inchange(kpis):
    k = kpis[0.0]
    assert k["tonnes_valorisees_j"] == 0 and k["recettes_valorisation_j_fcfa"] == {"menages": 0, "precollecteurs": 0, "total": 0}
    assert valorisation.facteur_collecte(Scenario.depuis_config()) == 1.0


def test_plus_de_tri_moins_de_dechets_a_collecter(kpis):
    a, b, c = kpis[0.0], kpis[0.3], kpis[0.6]
    assert a["tonnes_valorisees_j"] < b["tonnes_valorisees_j"] < c["tonnes_valorisees_j"]
    assert a["tonnes_non_evacuees_j"] > b["tonnes_non_evacuees_j"] > c["tonnes_non_evacuees_j"]
    assert a["taux_fuite"] > b["taux_fuite"] > c["taux_fuite"]
    assert a["tonnes_produites_j"] == b["tonnes_produites_j"] == c["tonnes_produites_j"]      # la production brute ne change pas


def test_tonnage_valorise_conforme_aux_hypotheses(kpis):
    v = charger_config().valorisation
    attendu = kpis[0.6]["tonnes_produites_j"] * 0.6 * v.part_valorisable * v.captation
    assert kpis[0.6]["tonnes_valorisees_j"] == pytest.approx(attendu, abs=0.1)


def test_recettes_partagees_entre_menages_et_precollecteurs(kpis):
    v = charger_config().valorisation
    r = kpis[0.6]["recettes_valorisation_j_fcfa"]
    assert abs(r["total"] - r["menages"] - r["precollecteurs"]) <= 1
    assert r["total"] == pytest.approx(kpis[0.6]["tonnes_valorisees_j"] * 1000 * v.prix_fcfa_kg, rel=0.01)
    assert r["menages"] == pytest.approx(r["total"] * v.part_revenu_menage, abs=1)


@pytest.mark.parametrize("mauvais", [-0.1, 1.5, "beaucoup", None])
def test_valeurs_invalides_refusees(mauvais):
    sc = Scenario.depuis_config().modifie(taux_tri=mauvais)
    with pytest.raises(ValueError):
        sc.valider()


def test_la_simulation_accumule_moins_de_dechets_avec_le_tri():
    sans = simuler(Scenario.depuis_config(), jours=20)["serie"][-1]["stock_depotoirs_tonnes"]
    avec = simuler(Scenario.depuis_config().modifie(taux_tri=0.6), jours=20)["serie"][-1]["stock_depotoirs_tonnes"]
    assert avec < sans
