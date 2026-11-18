"""Tests des tournées CVRP."""
import time

import pytest

from oregdo.planning import depotoirs, donnees, pmediane, tournees
from oregdo.planning.scenario import Scenario


@pytest.fixture(scope="module")
def ctx():
    d = donnees.charger()
    sc = Scenario.depuis_config()
    return d, sc, pmediane.resoudre(d, sc), [x for x in depotoirs.synthetiques(16, 1) if x.statut == "verifie"]  # indépendant de la base


def test_capacites_et_voyages(ctx):
    d, sc, pr, dep = ctx
    t = tournees.calculer(d, pr, dep, sc)
    assert t.voyages
    assert all(v["charge_kg"] <= sc.capacite_camion_kg for v in t.voyages)
    par_camion = {}
    for v in t.voyages:
        par_camion[v["camion"]] = par_camion.get(v["camion"], 0) + 1
    assert max(par_camion.values()) <= sc.voyages_max_par_jour


def test_camions_en_panne_exclus(ctx):
    d, sc, pr, dep = ctx
    sc2 = sc.modifie(camions_en_panne=[0, 1, 2, 3, 4])
    t = tournees.calculer(d, pr, dep, sc2)
    assert {v["camion"] for v in t.voyages}.isdisjoint({0, 1, 2, 3, 4})


def test_depotoirs_verifies_prioritaires(ctx):
    d, sc, pr, dep = ctx
    t = tournees.calculer(d, pr, dep, sc.modifie(camions_nombre=2))
    servis_dep = {a["id"] for v in t.voyages for a in v["arrets"] if a["type"] == "depotoir"}
    assert servis_dep == {x.id for x in dep}      # même avec 2 camions, tous les dépotoirs vérifiés sont pris


def test_aucun_camion(ctx):
    d, sc, pr, dep = ctx
    t = tournees.calculer(d, pr, dep, sc.modifie(camions_nombre=0))
    assert t.voyages == [] and t.non_servis


def test_determinisme(ctx):
    d, sc, pr, dep = ctx
    a, b = tournees.calculer(d, pr, dep, sc), tournees.calculer(d, pr, dep, sc)
    assert a.cout_fcfa == b.cout_fcfa and a.kg_collectes == b.kg_collectes


def test_temps_cvrp(ctx):
    d, sc, pr, dep = ctx
    t0 = time.perf_counter()
    tournees.calculer(d, pr, dep, sc)
    assert time.perf_counter() - t0 < 5
