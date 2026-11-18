"""Paramètres du moteur : tout vient de commune_config.yaml (section planification / simulation).

Quelques réglages purement techniques (temps de calcul, facteur de détour...) n'existent pas encore dans le
config racine : on les lit s'ils y sont (clé `planification.moteur`), sinon on prend les valeurs par défaut
ci-dessous, toutes marquées [H] (hypothèse) et à transférer dans commune_config.yaml.
"""
from types import SimpleNamespace

# Valeurs par défaut [H] des réglages absents du config racine.
DEFAUTS_MOTEUR = {
    "facteur_detour": 1.3,            # [H] rapport distance routière / distance à vol d'oiseau en ville
    "temps_milp_s": 10.0,             # plafond de sécurité du solveur p-médiane (HiGHS), l'optimum arrive en ~3 s
    "cvrp_solutions_max": 80,        # arrêt déterministe de la recherche (nombre d'améliorations) ; le temps n'est qu'un garde-fou
    "temps_cvrp_s": 3,                # garde-fou de temps ; la descente gloutonne s'arrête seule (déterministe)
    "graphe_routier": "graphe_routier.npz",   # graphe OSM du pack (scripts/build_osm_layers.py) ; vide ou absent : vol d'oiseau x détour
    "solveur_tournees": "pyvrp",      # "pyvrp" (recherche génétique hybride, MIT) ou "ortools" (descente gloutonne, repli)
    "pyvrp_iterations": 200,          # arrêt déterministe (~1,5 s pour ~300 arrêts) ; plus = meilleur mais plus lent
    "pyvrp_temps_max_s": 10.0,        # garde-fou de temps seulement
    "facteur_service_pyvrp": 10,      # [H] la prime de service d'un arrêt vaut la pénalité d'OR-Tools x ce facteur (servir d'abord)
    "stock_depotoir_kg": 1500,        # [H] tonnage à enlever par dépotoir vérifié sans volume connu
    "penalite_pr_m_par_tonne": 20000, # [H] pénalité (en mètres) pour un PR non visité, par tonne non collectée
    "priorite_depotoir": 5.0,         # [H] un dépotoir vérifié pèse 5 fois un PR à tonnage égal
    "vitesse_kmh": 25,                # [H] vitesse moyenne d'un camion en ville
    "temps_service_min": 15,          # [H] chargement par arrêt
    "duree_journee_h": 8,             # [H] durée de travail d'un camion
    "resolution_nouveau_quartier_m": 400,  # [H] maille des îlots générés pour un nouveau quartier
    # --- simulation multi-agents (réglages [H]) ---
    "tarif_quartier_populaire_fcfa": 500,       # [S] tarif d'abonnement mensuel en quartier non loti
    "voyages_pre_collecteur_par_jour": 3,       # [H] voyages d'un tricycle vers le PR
    "apport_volontaire_non_abonnes": 0.197,     # [S dérivé] part des déchets des non-abonnés portée au PR s'il est à portée
    "stock_max_jours_pr": 3,                    # [H] un PR déborde au-delà de 3 jours de capacité
    "seuil_depotoir_actif_kg": 500,             # [H] stock au-delà duquel un dépotoir est « actif »
    "rayon_apparition_depotoir_m": 1500,         # [H] un dépotoir naît si aucun n'existe à moins de ce rayon
    "delai_verification_jours": 7,              # [H] délai avant qu'un nouveau dépotoir soit vérifié
    "variabilite_production": 0.1,              # [H] bruit journalier de production (écart relatif)
    "reduction_sensibilisation": 0.1,           # [H] baisse des dépôts sauvages après sensibilisation
    "duree_effet_jours": 45,                    # [H] durée de l'effet d'une intervention avant rechute
    "reduction_sanction": 0.25,                  # [H] baisse après sanction
    "interventions_par_agent_jour": 0.25,        # [H] interventions de la brigade par agent et par jour
    "contrevenants_par_intervention": 1,        # [H] amendes émises par intervention de sanction
    "taux_recouvrement_amendes": 0.3,           # [H] part des amendes réellement payées (sanctions « rarement appliquées »)
    "cout_agent_brigade_jour_fcfa": 5000,       # [H]
    "part_depots_auteur_identifiable": 0.15,    # [H] auteur identifiable (repli)
    "rayon_risque_inondation_m": 200,           # [H] repli
    "rendement_capacite_supplementaire": 0.8,   # [H] repli
    "tolerance_stock_relative": 0.02,           # [H] repli
    "conversion_abonnement_apres_sensibilisation": 0.03,   # [H] part de non-abonnés qui s'abonnent
    # --- agents individuels (option « agents_individuels » du scénario) ---
    "panne_tricycle_prob_jour": 0.05,           # [H] chance qu'un tricycle tombe en panne un jour donné
    "panne_tricycle_duree_jours": 2,            # [H] durée d'une panne de tricycle
    "heterogeneite_tricycle": 0.25,             # [H] écart relatif de capacité d'un tricycle à l'autre
    "absence_agent_brigade_prob_jour": 0.05,    # [H] chance qu'un agent de la brigade soit absent (maladie, mission) un jour donné
    "absence_agent_brigade_duree_jours": 2,     # [H] durée d'une absence
    # --- mairie décisionnelle (option « mairie_decisionnelle » du scénario) ---
    "periode_decision_mairie_jours": 14,        # [H] la mairie réexamine le stock de dépotoirs tous les 14 jours
    "seuil_hausse_stock_decision": 0.05,        # [H] hausse relative du stock sur la période qui déclenche un achat
    "camions_par_decision": 2,                  # [H] camions achetés à chaque décision
    "budget_camions_supplementaires_fcfa": 300_000_000,   # [H] enveloppe maximale pour de nouveaux camions
}


def moteur(cfg) -> SimpleNamespace:
    """Renvoie les réglages techniques : config si présents, sinon défauts."""
    voulu = dict(DEFAUTS_MOTEUR)
    brut = getattr(getattr(cfg, "planification", None), "moteur", None)
    if brut is not None:
        voulu.update(vars(brut))
    return SimpleNamespace(**voulu)
