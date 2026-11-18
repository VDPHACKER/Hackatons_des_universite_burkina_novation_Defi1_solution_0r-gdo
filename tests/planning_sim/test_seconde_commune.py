"""Réutilisabilité : le même moteur doit fonctionner sur une seconde commune (Bobo-Dioulasso) sans changer une ligne de code.

Le pack packs/bobo/ est créé par scripts/creer_pack_commune.py à partir d'OpenStreetMap et d'Open Buildings.
Les chiffres officiels viennent de la monographie INSD du RGPH 2019 (population urbaine 904 920, 7 arrondissements, 33 secteurs,
ramassage privé 37,3 % des ménages)."""
import dataclasses
from pathlib import Path

import numpy as np
import pytest

from oregdo.config import charger_config
from oregdo.geo import couche
from oregdo.planning import arrondissement, depotoirs
from oregdo.planning.plan import calculer_plan_detaille
from oregdo.planning.scenario import Scenario
from oregdo.simulation.modele import simuler

C = "bobo"
PACK = Path(__file__).resolve().parents[2] / "packs" / C
pytestmark = pytest.mark.skipif(not (PACK / "commune_config.yaml").exists(), reason="pack bobo non créé (scripts/creer_pack_commune.py)")


@pytest.fixture(scope="module")
def cfg():
    return charger_config(C)


@pytest.fixture(scope="module")
def sc():
    return Scenario.depuis_config(C)


@pytest.fixture(scope="module")
def dep():
    return [dataclasses.replace(x, statut="verifie") for x in depotoirs.synthetiques(40, 20260116, C)]


@pytest.fixture(scope="module")
def detail(sc, dep):
    return calculer_plan_detaille(sc, C, depotoirs=dep)


def test_la_configuration_porte_les_chiffres_officiels_de_bobo(cfg):
    assert cfg.commune.code == C and cfg.commune.nom == "Bobo-Dioulasso"
    assert cfg.demographie.population == 904920 and cfg.demographie.taux_abonnement == pytest.approx(0.373)
    m = cfg.demographie.modes_evacuation
    assert sum(vars(m).values()) == pytest.approx(1.0, abs=0.001)                  # les modes d'évacuation couvrent 100 % des ménages
    # coefficients dérivés des chiffres de Bobo (et non copiés d'Ouagadougou : 0,59 et 0,197)
    assert cfg.simulation.fuite_vers_depotoir_si_pr_inaccessible == pytest.approx((m.tas_immondices + m.rue) / (1 - 0.373), abs=0.01)
    assert cfg.planification.moteur.apport_volontaire_non_abonnes == pytest.approx(m.bac_a_ordures / (1 - 0.373), abs=0.002)
    # ressources mises à l'échelle : moins de camions et de budget qu'à Ouagadougou (40 camions, 250 M FCFA)
    assert 10 <= cfg.planification.camions.nombre <= 20 and cfg.planification.budget_pr_fcfa < 150_000_000


def test_le_pack_est_complet_et_honnete_sur_ses_donnees():
    for nom in ("commune", "secteurs", "eau", "routes", "ilots", "sites_candidats", "infrastructures"):
        assert len(couche(nom, C)) > 0, nom
    ilots, secteurs = couche("ilots", C), couche("secteurs", C)
    assert ilots["population"].sum() == pytest.approx(904920, abs=50)              # la population répartie retombe sur le total officiel
    assert len(secteurs) == 33 and secteurs["arrondissement"].nunique() == 7       # nombres officiels
    assert ilots["synthetique"].all() and secteurs["synthetique"].all()             # contours dits synthétiques
    assert (ilots["source_population"] == "open_buildings").all() and ilots["modelise"].all()
    assert bool(couche("commune", C)["synthetique"].iloc[0])                        # limite déduite des bâtiments : dite telle


def test_le_plan_se_calcule_sur_bobo_et_reste_coherent(detail, sc):
    k = detail["plan"]["kpi"]
    assert k["statut_pmediane"] == "optimal" and k["nb_pr"] > 20
    assert 0.2 <= k["taux_couverture_production"] <= 0.8 and 0 <= k["taux_fuite"] <= 1
    assert k["camions_utilises"] <= sc.camions_nombre and k["tonnes_produites_j"] == pytest.approx(904920 * 0.57 / 1000, rel=0.01)
    assert detail["plan"]["tournees"]["features"], "aucune tournée"
    assert all(len(f["geometry"]["coordinates"]) >= 2 for f in detail["plan"]["tournees"]["features"])


def test_les_arrondissements_de_bobo_retombent_sur_le_total(detail, sc):
    t = arrondissement.tableau(detail, sc, C)["arrondissements"]
    assert len(t) == 7
    assert sum(x["population"] for x in t) == pytest.approx(904920, abs=50)
    assert sum(x["nb_pr"] for x in t) == detail["plan"]["kpi"]["nb_pr"]
    p = arrondissement.plan_arrondissement(detail, sc, "a03", C)
    assert p["arrondissement"]["nom"] == "Arrondissement 3" and p["contour"]["geometry"]["type"] in ("Polygon", "MultiPolygon")


def test_les_aleas_du_jury_fonctionnent_sur_bobo(sc, dep, detail):
    base = detail["plan"]["kpi"]
    pluies = calculer_plan_detaille(sc.modifie(saison_pluies=True), C, depotoirs=dep)["plan"]["kpi"]
    assert pluies["distance_km"] > base["distance_km"]                             # les pistes coupées allongent les tournées
    panne = sc.modifie(camions_en_panne=[0, 1, 2])
    panne.valider(C)
    k = calculer_plan_detaille(panne, C, depotoirs=dep)["plan"]
    assert k["kpi"]["camions_disponibles"] == sc.camions_nombre - 3
    assert {f["properties"]["camion"] for f in k["tournees"]["features"]}.isdisjoint({0, 1, 2})


def test_la_simulation_multi_agents_tourne_sur_bobo(sc):
    r = simuler(sc, jours=15, commune=C)
    d = r["diagnostic"]
    assert len(r["serie"]) == 15 and d["tendance_stock"] in ("croissant", "stable", "decroissant")
    assert np.isfinite([s["stock_depotoirs_tonnes"] for s in r["serie"]]).all()
