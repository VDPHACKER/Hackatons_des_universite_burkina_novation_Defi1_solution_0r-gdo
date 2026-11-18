"""Tests de la localisation des PR."""
import time

import numpy as np
import pytest

from oregdo.planning import donnees, pmediane
from oregdo.planning.scenario import Scenario


@pytest.fixture(scope="module")
def base():
    return donnees.charger()


def test_budget_et_capacite_respectes(base):
    sc = Scenario.depuis_config()
    r = pmediane.resoudre(base, sc)
    assert r.cout_fcfa <= sc.budget_pr_fcfa + 1e-6
    assert len(r.retenus) > 0
    assert np.all(r.charge_kg_j <= base.sites_cap_kg_j[r.retenus] + 1e-6)
    assert 0 < r.couverture <= 1


def test_rayon_respecte_en_distance_euclidienne(base):
    sc = Scenario.depuis_config()
    r = pmediane.resoudre(base, sc)
    servis = np.flatnonzero(r.affectation >= 0)
    d = np.linalg.norm(base.ilots_xy[servis] - base.sites_xy[r.affectation[servis]], axis=1)
    assert d.max() <= sc.rayon_acces_pr_m  # le coût effectif (détour >= 1) borne la distance directe


def test_plus_de_budget_plus_de_couverture(base):
    sc = Scenario.depuis_config()
    petit = pmediane.resoudre(base, sc.modifie(budget_pr_fcfa=sc.budget_pr_fcfa / 3))
    grand = pmediane.resoudre(base, sc)
    assert grand.couverture >= petit.couverture


def test_determinisme(base):
    sc = Scenario.depuis_config()
    a, b = pmediane.resoudre(base, sc), pmediane.resoudre(base, sc)
    assert list(a.retenus) == list(b.retenus)


def test_budget_nul(base):
    r = pmediane.resoudre(base, Scenario.depuis_config().modifie(budget_pr_fcfa=0))
    assert len(r.retenus) == 0 and r.couverture == 0


def test_temps_resolution_mesure(base):
    t = time.perf_counter()
    pmediane.resoudre(base, Scenario.depuis_config())
    assert time.perf_counter() - t < 5
