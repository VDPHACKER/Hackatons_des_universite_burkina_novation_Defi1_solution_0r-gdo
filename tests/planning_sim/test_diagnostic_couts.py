"""Diagnostic honnête, coûts séparés, risque d'inondation, amendes prudentes (corrections après le jury)."""
import pytest

from oregdo.config import charger_config
from oregdo.planning import depotoirs
from oregdo.planning.plan import calculer_plan
from oregdo.planning.scenario import Scenario
from oregdo.simulation.comparaison import comparer
from oregdo.simulation.modele import simuler

SYN = depotoirs.synthetiques(16, 1)   # indépendant de la base de l'application
JOURS = 40


@pytest.fixture(scope="module")
def sc():
    return Scenario.depuis_config()


@pytest.fixture(scope="module")
def run(sc):
    return simuler(sc, jours=JOURS)


# --- 1. diagnostic ---
def test_diagnostic_calcule_et_coherent(run):
    d = run["diagnostic"]
    serie = run["serie"]
    assert d["stock_initial_tonnes"] == serie[0]["stock_depotoirs_tonnes"]
    assert d["stock_final_tonnes"] == serie[-1]["stock_depotoirs_tonnes"]
    # Bilan : le stock varie de (fuite - enlevé) par jour. fuite et enlevé sont moyennés sur les 10 derniers jours,
    # donc on compare à la pente du stock sur ces mêmes 10 jours (la pente globale inclut le régime de démarrage).
    bilan = d["fuite_vers_depotoirs_t_par_jour"] - d["tonnes_enlevees_depotoirs_t_par_jour"]
    fin = [s["stock_depotoirs_tonnes"] for s in serie[-10:]]
    pente_fin = (fin[-1] - fin[0]) / (len(fin) - 1)
    assert pente_fin == pytest.approx(bilan, rel=0.10, abs=5)
    assert d["variation_stock_t_par_jour"] > 0 and d["variation_stock_t_par_jour"] >= 0.8 * bilan   # le démarrage ne l'inverse pas
    assert d["tendance_stock"] == "croissant" and d["stable"] is False
    assert d["camions_supplementaires_pour_stabiliser"] >= 1
    assert "ne suffit pas" in d["message"] and "camions" in d["message"]
    assert run["nature"] == "plan_cible" and "pas la situation actuelle" in run["description"]


def test_diagnostic_stable_avec_les_camions_indiques(sc, run):
    n = run["diagnostic"]["camions_supplementaires_pour_stabiliser"]
    mieux = simuler(sc.modifie(camions_nombre=sc.camions_nombre + n), jours=JOURS)["diagnostic"]
    assert mieux["variation_stock_t_par_jour"] < run["diagnostic"]["variation_stock_t_par_jour"] / 2
    assert mieux["tendance_stock"] in ("stable", "decroissant") or mieux["variation_stock_t_par_jour"] < 0.1 * run["diagnostic"]["variation_stock_t_par_jour"]


def test_diagnostic_stable_sans_fuite(sc):
    """Sans fuite (tous les PR à portée, aucun dépôt) le diagnostic ne doit pas alarmer : on force la fuite à 0."""
    cfg = charger_config("ouaga")
    ancien = cfg.simulation.fuite_vers_depotoir_si_pr_inaccessible
    cfg.simulation.fuite_vers_depotoir_si_pr_inaccessible = 0.0
    try:
        d = simuler(sc, jours=15)["diagnostic"]
    finally:
        cfg.simulation.fuite_vers_depotoir_si_pr_inaccessible = ancien
    assert d["tendance_stock"] != "croissant" or d["variation_stock_t_par_jour"] < 5


def test_comparaison_expose_plan_cible_et_diagnostic(sc):
    c = comparer(sc, sc.modifie(camions_nombre=50), jours=15)
    assert c["plan_cible"] is c["reference"] and "diagnostic" in c and "diagnostic_plan_cible" in c
    assert c["scenario"]["diagnostic"]["camions_actuels"] == 50


# --- 2. coûts séparés ---
def test_cout_par_tonne_detail_et_banque_mondiale(sc):
    k = calculer_plan(sc, depotoirs=SYN)["kpi"]
    d = k["cout_par_tonne_detail"]
    assert d["total_fcfa"] == d["carburant"] + d["personnel"] + d["vehicules"] + d["pr"]
    assert d["carburant"] < d["total_fcfa"] and d["personnel"] > 0 and d["vehicules"] > 0 and d["pr"] > 0
    assert k["cout_par_tonne_fcfa"] == d["total_fcfa"]
    bas, haut = d["reference_banque_mondiale_fcfa"]
    assert bas < haut and d["total_fcfa"] < bas          # écart reconnu, pas masqué
    assert "fois plus bas" in d["message"]
    assert k["depenses_mairie_j_fcfa"]["total"] == sum(v for c, v in k["depenses_mairie_j_fcfa"].items() if c != "total")


def test_comptes_separes(run):
    c, f = run["comptes"], run["final"]
    assert set(c) == {"mairie", "pre_collecteurs", "amendes"}
    assert c["pre_collecteurs"]["recettes_abonnement_fcfa"] == f["recettes_abonnement_fcfa"] > 0
    m = c["mairie"]
    assert m["depenses_totales_fcfa"] == pytest.approx(
        m["carburant_fcfa"] + m["personnel_fcfa"] + m["vehicules_fcfa"] + m["amortissement_pr_fcfa"] + m["brigade_fcfa"], rel=0.01)
    # Le budget consommé ne contient ni recettes d'abonnement ni amendes.
    assert f["budget_consomme_fcfa"] == pytest.approx(m["investissement_pr_fcfa"] + m["depenses_exploitation_fcfa"], rel=0.01)
    assert f["budget_consomme_fcfa"] < m["investissement_pr_fcfa"] + m["depenses_exploitation_fcfa"] + f["recettes_abonnement_fcfa"]


def test_cout_hausse_en_cas_de_pluie(sc):
    a = calculer_plan(sc, depotoirs=SYN)["kpi"]["cout_par_tonne_fcfa"]
    b = calculer_plan(sc.modifie(saison_pluies=True), depotoirs=SYN)["kpi"]["cout_par_tonne_fcfa"]
    assert b > a


# --- 3. pluie, caniveau, brûlage ---
def test_risque_inondation_et_flux_caniveau_brulage(sc):
    sec = simuler(sc, jours=15)
    pluie = simuler(sc.modifie(saison_pluies=True), jours=15)
    assert all(s["depotoirs_a_risque_inondation"] == 0 for s in sec["serie"])        # hors saison : aucun risque déclaré
    assert pluie["serie"][-1]["depotoirs_a_risque_inondation"] == pluie["serie"][-1]["depotoirs_proches_eau_actifs"] > 0
    assert pluie["final"]["depotoirs_a_risque_inondation_saison_pluies"] > 0
    f = sec["final"]
    assert f["tonnes_caniveau_totales"] > 0 and f["tonnes_brulees_totales"] > 0
    # Bilan de masse du déchet non collecté : dépôt + caniveau + brûlé + collecté ~ produit.
    total = f["tonnes_fuite_totales"] + f["tonnes_caniveau_totales"] + f["tonnes_brulees_totales"] + \
        sum(s["tonnes_produites"] for s in sec["serie"]) * sec["serie"][-1]["taux_couverture"]
    assert total == pytest.approx(f["tonnes_produites_totales"], rel=0.1)


def test_part_caniveau_derivee_du_rgph(sc):
    mo = charger_config().demographie.modes_evacuation
    attendu = mo.fosse_caniveau / (1 - mo.ramassage_prive)
    f = simuler(sc, jours=3)["final"]
    assert 0 < f["tonnes_caniveau_totales"] < f["tonnes_produites_totales"] * attendu


# --- 4. amendes ---
def test_amendes_prudentes_et_comptees(sc):
    cfg = charger_config()
    assert cfg.planification.moteur.contrevenants_par_intervention <= 1
    assert 0 < cfg.planification.moteur.part_depots_auteur_identifiable < 0.5
    a = simuler(sc, jours=60)
    c = a["comptes"]["amendes"]
    assert c["sanctions"] > 0 and c["amendes_emises"] <= c["sanctions"]
    assert c["montant_recouvre_fcfa"] == pytest.approx(c["montant_emis_fcfa"] * c["taux_recouvrement"], rel=0.02, abs=2)


def test_sanctions_seulement_sur_depotoirs_verifies(sc, monkeypatch):
    """Si tous les dépotoirs sont « à confirmer », la brigade sensibilise mais ne sanctionne jamais."""
    from oregdo.simulation import modele
    import dataclasses
    tous = [dataclasses.replace(d, statut="a_confirmer") for d in depotoirs.synthetiques(16, 1) if d.statut != "rejete"]
    monkeypatch.setattr(modele.acces_depotoirs, "lire_tous", lambda *a, **k: tous)
    monkeypatch.setattr(modele.Depotoir, "step", lambda self: None)     # pas de vérification automatique au bout de 7 jours
    r = simuler(sc, jours=40)
    assert sum(s["sensibilisations"] for s in r["serie"]) > 0
    # Les dépotoirs nés pendant la simulation restent à confirmer aussi : aucune sanction possible.
    assert sum(s["sanctions"] for s in r["serie"]) == 0 and r["final"]["recettes_amendes_fcfa"] == 0
