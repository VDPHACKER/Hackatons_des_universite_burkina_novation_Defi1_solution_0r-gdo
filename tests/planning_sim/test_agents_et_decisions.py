"""Simulation multi-agents : tricycles individuels et mairie qui décide (options du scénario, désactivées par défaut)."""
from types import SimpleNamespace

import pytest

from oregdo.config import charger_config
from oregdo.planning.parametres import moteur as moteur_reel
from oregdo.planning.plan import calculer_plan_detaille
from oregdo.planning.scenario import Scenario
from oregdo.simulation import modele
from oregdo.simulation.modele import ModeleOregdo, simuler

JOURS = 60


@pytest.fixture(scope="module")
def sc():
    return Scenario.depuis_config()


@pytest.fixture(scope="module")
def plan(sc):
    return calculer_plan_detaille(sc)


@pytest.fixture(scope="module")
def sans_option(sc, plan):
    return simuler(sc, jours=JOURS, plan=plan)


@pytest.fixture(scope="module")
def avec_decisions(sc, plan):
    return simuler(sc.modifie(mairie_decisionnelle=True), jours=JOURS, plan=plan)


def test_les_options_sont_desactivees_par_defaut_et_validees(sc, sans_option):
    assert sc.agents_individuels is False and sc.mairie_decisionnelle is False
    assert sans_option["decisions_mairie"] == [] and "tricycles_en_panne" not in sans_option["serie"][0]
    assert sans_option["options"] == {"agents_individuels": False, "mairie_decisionnelle": False}
    for nom in ("agents_individuels", "mairie_decisionnelle"):
        with pytest.raises(ValueError, match="vrai ou faux"):
            sc.modifie(**{nom: "oui"}).valider()


def test_les_tricycles_sont_des_agents_distincts_avec_pannes(sc, plan):
    m = ModeleOregdo(sc.modifie(agents_individuels=True), plan=plan)
    n_secteurs = len(m.pre_collecteurs)
    attendu = round(charger_config().simulation.pre_collecteurs.nombre_par_secteur)
    tous = [t for g in m.pre_collecteurs.values() for t in g.tricycles]
    assert len(tous) == n_secteurs * max(1, attendu) and len(tous) > n_secteurs               # un agent par tricycle
    assert len({round(t.capacite_jour) for t in tous}) > 1                                      # capacités hétérogènes
    for _ in range(30):
        m.step()
    assert max(s["tricycles_en_panne"] for s in m.serie) > 0                                    # des pannes surviennent
    en_panne = [t for t in tous if t.en_panne]
    assert all(t.capacite_effective() == 0.0 for t in en_panne)                                 # un tricycle en panne ne collecte rien


def test_la_brigade_est_composee_d_agents_qui_peuvent_etre_absents(sc, plan):
    m = ModeleOregdo(sc.modifie(agents_individuels=True), plan=plan)
    effectif = int(charger_config().simulation.brigade_laabal.effectif)
    assert len(m.brigade.agents) == effectif > 1                                               # un agent par membre de la brigade
    for _ in range(40):
        m.step()
    assert max(s["agents_brigade_absents"] for s in m.serie) > 0                               # des absences surviennent
    assert all(a.interventions_du_jour() >= 0 for a in m.brigade.agents)
    defaut = ModeleOregdo(sc, plan=plan)
    assert defaut.brigade.agents == [] and "agents_brigade_absents" not in (defaut.serie[0] if defaut.serie else {})   # sans l'option : budget commun, inchangé


def test_les_agents_individuels_sont_reproductibles_par_graine(sc, plan):
    a = simuler(sc.modifie(agents_individuels=True), jours=15, graine=5, plan=plan)
    b = simuler(sc.modifie(agents_individuels=True), jours=15, graine=5, plan=plan)
    c = simuler(sc.modifie(agents_individuels=True), jours=15, graine=6, plan=plan)
    assert a["serie"] == b["serie"] and a["serie"] != c["serie"]


def test_la_mairie_decide_d_acheter_des_camions_quand_le_stock_grossit(sc, sans_option, avec_decisions):
    assert sans_option["diagnostic"]["tendance_stock"] == "croissant"                            # situation de départ : le stock grossit
    tout = avec_decisions["decisions_mairie"]
    d = [x for x in tout if x["camions"] > 0]                                                   # les achats ; les refus (enveloppe vide) sont testés à part
    assert d, "la mairie aurait dû décider d'acheter des camions"
    p = moteur_reel(charger_config())
    assert all(x["jour"] % p.periode_decision_mairie_jours == 0 and x["jour"] > p.periode_decision_mairie_jours for x in tout)   # le 1er examen sert de point de départ
    assert all(x["camions"] <= p.camions_par_decision and "achat" in x["message"] and x["hausse_pct"] > 100 * p.seuil_hausse_stock_decision for x in d)
    assert sum(x["investissement_fcfa"] for x in d) <= p.budget_camions_supplementaires_fcfa
    assert avec_decisions["serie"][-1]["camions_achetes_cumules"] == sum(x["camions"] for x in d)
    assert avec_decisions["comptes"]["mairie"]["investissement_camions_decides_fcfa"] == sum(x["investissement_fcfa"] for x in d)


def test_le_diagnostic_compte_les_camions_achetes_par_la_mairie(sc, sans_option, avec_decisions):
    achetes = avec_decisions["serie"][-1]["camions_achetes_cumules"]
    assert achetes > 0
    assert avec_decisions["diagnostic"]["camions_actuels"] == len(sc.camions_disponibles()) + achetes
    assert avec_decisions["diagnostic"]["camions_necessaires"] == avec_decisions["diagnostic"]["camions_actuels"] + (avec_decisions["diagnostic"]["camions_supplementaires_pour_stabiliser"] or 0)
    assert sans_option["diagnostic"]["camions_actuels"] == len(sc.camions_disponibles())          # sans option : décompte inchangé


def test_les_decisions_freinent_le_stock_et_leur_cout_est_dans_le_budget(sans_option, avec_decisions):
    assert avec_decisions["final"]["stock_depotoirs_fin_tonnes"] < sans_option["final"]["stock_depotoirs_fin_tonnes"]
    assert avec_decisions["final"]["budget_consomme_fcfa"] > sans_option["final"]["budget_consomme_fcfa"]    # l'achat est bien compté


def test_la_mairie_ne_depasse_jamais_l_enveloppe(sc, plan, monkeypatch):
    prix = charger_config().planification.couts.prix_camion_fcfa
    petit = lambda cfg: SimpleNamespace(**{**vars(moteur_reel(cfg)), "budget_camions_supplementaires_fcfa": 3 * prix})   # noqa: E731
    monkeypatch.setattr(modele, "moteur", petit)
    r = simuler(sc.modifie(mairie_decisionnelle=True), jours=JOURS, plan=plan)
    achetes = sum(x["camions"] for x in r["decisions_mairie"])
    assert 0 < achetes <= 3
    assert any(x["camions"] == 0 and "épuisée" in x["message"] for x in r["decisions_mairie"])      # elle le dit quand l'enveloppe est vide
