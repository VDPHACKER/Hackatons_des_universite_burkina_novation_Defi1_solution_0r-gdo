"""Tests du plan complet et des quatre aléas (temps réels mesurés)."""
import time

import pytest

from oregdo.planning import aleas, depotoirs
from oregdo.planning.plan import calculer_plan
from oregdo.planning.scenario import Scenario

SYN = depotoirs.synthetiques(16, 1)   # indépendant de la base de l'application
GRANDE_LISTE = depotoirs.synthetiques(200, 2)   # ~100 vérifiés : taille réaliste, déterministe
QUARTIER = {"nom": "Test", "population": 40000, "polygone": {"type": "Polygon", "coordinates": [[
    [-1.60, 12.30], [-1.585, 12.30], [-1.585, 12.315], [-1.60, 12.315], [-1.60, 12.30]]]}}


@pytest.fixture(scope="module")
def base():
    sc = Scenario.depuis_config()
    return sc, calculer_plan(sc, depotoirs=SYN)


def test_plan_coherent(base):
    sc, p = base
    k = p["kpi"]
    assert k["cout_investissement_pr_fcfa"] <= sc.budget_pr_fcfa
    assert all(f["properties"]["charge_kg"] <= sc.capacite_camion_kg for f in p["tournees"]["features"])
    assert all(f["geometry"]["type"] == "LineString" for f in p["tournees"]["features"])
    assert k["tonnes_evacuees_j"] + k["tonnes_non_evacuees_j"] == pytest.approx(k["tonnes_produites_j"], abs=0.2)
    assert k["tonnes_fuite_j"] <= k["tonnes_non_evacuees_j"]


def test_determinisme_plan(base):
    sc, p = base
    assert calculer_plan(sc, depotoirs=SYN)["empreinte"] == p["empreinte"]


def test_panne_aucun_camion_en_panne_dans_les_tournees(base):
    sc, p = base
    sc2, msg = aleas.appliquer(sc, "panne_camion", {"camions": [0, 1, 2, 3, 4, 5]})
    p2 = calculer_plan(sc2, depotoirs=SYN)
    assert {f["properties"]["camion"] for f in p2["tournees"]["features"]}.isdisjoint({0, 1, 2, 3, 4, 5})
    assert "en panne" in msg and p2["kpi"]["camions_disponibles"] == sc.camions_nombre - 6


def test_pluie_cout_en_hausse_et_couverture_mesuree(base):
    sc, p = base
    sc2, _ = aleas.appliquer(sc, "saison_pluies", {})
    p2 = calculer_plan(sc2, depotoirs=SYN)
    print("pluie :", p["kpi"]["cout_collecte_fcfa"], "->", p2["kpi"]["cout_collecte_fcfa"],
          "| couverture", p["kpi"]["couverture_pr"], "->", p2["kpi"]["couverture_pr"])
    assert p2["kpi"]["cout_par_tonne_fcfa"] > p["kpi"]["cout_par_tonne_fcfa"]
    assert p2["kpi"]["couverture_pr"] <= p["kpi"]["couverture_pr"]


def test_nouveau_quartier(base):
    sc, p = base
    sc2, _ = aleas.appliquer(sc, "nouveau_quartier", QUARTIER)
    p2 = calculer_plan(sc2, depotoirs=SYN)
    assert p2["kpi"]["tonnes_produites_j"] > p["kpi"]["tonnes_produites_j"]
    assert any(f["properties"]["id"].startswith("Test-C") for f in p2["pr"]["features"])


def test_signalements_pieges_ne_changent_pas_le_plan(base):
    sc, p = base
    faux = [{"id": f"P{i}", "lon": -1.53, "lat": 12.37, "statut": "rejete"} for i in range(50)]
    sc2, msg = aleas.appliquer(sc, "signalements_pieges", {"signalements": faux})
    assert sc2.signalements_pieges_recus == 50
    assert calculer_plan(sc2, depotoirs=SYN)["empreinte"] == p["empreinte"]
    # Même des dépotoirs rejetés ou à confirmer transmis au moteur sont écartés :
    rejetes = [d for d in SYN if d.statut != "verifie"]
    assert rejetes
    avec = calculer_plan(sc, depotoirs=rejetes)
    assert avec["kpi"]["nb_depotoirs_verifies"] == 0


def test_aleas_invalides(base):
    sc, _ = base
    with pytest.raises(ValueError):
        aleas.appliquer(sc, "meteorite")
    with pytest.raises(ValueError):
        aleas.appliquer(sc, "panne_camion", {"camions": [999]})
    with pytest.raises(ValueError):
        aleas.appliquer(sc, "nouveau_quartier", {"population": 10})


def test_temps_de_recalcul_en_direct(base):
    sc, _ = base
    # Le serveur chauffe le réseau au démarrage (distances entre points fixes, puis une ligne de graphe par dépotoir, ~30 ms chacune,
    # gardée en mémoire) : on mesure le recalcul en direct une fois ce calcul unique fait, comme pendant l'épreuve.
    calculer_plan(sc, depotoirs=GRANDE_LISTE)
    calculer_plan(sc.modifie(saison_pluies=True), depotoirs=GRANDE_LISTE)
    mesures = {}
    for nom, (typ, par) in {"panne": ("panne_camion", {"nombre": 5}), "pluie": ("saison_pluies", {}),
                            "quartier": ("nouveau_quartier", QUARTIER)}.items():
        sc2, _ = aleas.appliquer(sc, typ, par)
        t = time.perf_counter()
        calculer_plan(sc2, depotoirs=GRANDE_LISTE)   # ~100 dépotoirs vérifiés, comme la base de démonstration
        mesures[nom] = round(time.perf_counter() - t, 2)
    print("temps de recalcul (s) :", mesures)
    assert max(mesures.values()) < 5


def test_panne_camion_accepte_un_nombre():
    """L'interface envoie le nombre de camions en panne, pas leurs identifiants (régression d'intégration)."""
    from oregdo.planning import aleas
    from oregdo.planning.scenario import Scenario
    sc = Scenario.depuis_config()
    sc2, message = aleas.appliquer(sc, "panne_camion", {"camions": 5})
    assert len(sc2.camions_en_panne) == 5
    assert "5 camion(s) en panne" in message
