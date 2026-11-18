"""Coût complet de la collecte secondaire (dépenses de la mairie) : carburant, personnel, véhicules, PR.

Tous les paramètres viennent de planification.couts (hypothèses [H] ; références Banque mondiale [S]).
Le périmètre exclut la pré-collecte (financée par les abonnements des ménages), le CET (redevance de Polesgo,
non documentée) et les frais généraux de la mairie : le coût est donc un MINIMUM, à comparer à la Banque mondiale.
"""
from ..config import COMMUNE_DEFAUT, charger_config


def par_camion_jour(cfg) -> dict:
    """Coûts fixes d'un camion et de son équipage par jour de travail (hors carburant)."""
    c = cfg.planification.couts
    personnel = c.salaire_chauffeur_jour_fcfa + c.ripeurs_par_camion * c.salaire_ripeur_jour_fcfa
    amortissement = c.prix_camion_fcfa / (c.duree_vie_camion_ans * 365)
    entretien = c.prix_camion_fcfa * c.entretien_camion_taux_annuel / 365
    return {"personnel": personnel, "amortissement": amortissement, "entretien": entretien}


def composantes(sc, camions_utilises: int, distance_effective_m: float, investissement_pr_fcfa: float,
                commune: str = COMMUNE_DEFAUT) -> dict:
    """Coûts d'une tournée (carburant, personnel des camions utilisés) et coûts quotidiens (véhicules, PR)."""
    cfg = charger_config(commune)
    pc = par_camion_jour(cfg)
    return {
        "carburant_tournee": distance_effective_m / 1000.0 * cfg.planification.camions.cout_km_fcfa,
        "personnel_tournee": camions_utilises * pc["personnel"],
        # La flotte entière (pannes comprises) s'amortit et s'entretient.
        "vehicules_amortissement_jour": sc.camions_nombre * pc["amortissement"],
        "vehicules_entretien_jour": sc.camions_nombre * pc["entretien"],
        "pr_jour": investissement_pr_fcfa / (cfg.planification.couts.duree_amortissement_pr_ans * 365),
    }


def detail_par_tonne(comp: dict, tonnes_tournee: float, frequence_jours: int, commune: str = COMMUNE_DEFAUT) -> dict:
    """Coût par tonne collectée par composante, total, et écart avec la fourchette de la Banque mondiale."""
    if tonnes_tournee <= 0:
        return {"carburant": None, "personnel": None, "vehicules": None, "pr": None, "total_fcfa": None,
                "reference_banque_mondiale_fcfa": None, "message": "Aucune tonne collectée : coût par tonne non défini."}
    f = frequence_jours
    d = {"carburant": comp["carburant_tournee"], "personnel": comp["personnel_tournee"],
         "vehicules": (comp["vehicules_amortissement_jour"] + comp["vehicules_entretien_jour"]) * f,
         "pr": comp["pr_jour"] * f}
    d = {k: round(v / tonnes_tournee) for k, v in d.items()}
    d["total_fcfa"] = sum(d.values())
    d.update(_comparaison_banque_mondiale(d["total_fcfa"], commune))
    return d


def _comparaison_banque_mondiale(total: float, commune: str) -> dict:
    ref = charger_config(commune).planification.couts.reference_banque_mondiale
    bas = round((ref.transport_usd_par_tonne[0] + ref.exploitation_usd_par_tonne) * ref.usd_fcfa)
    haut = round((ref.transport_usd_par_tonne[1] + ref.exploitation_usd_par_tonne) * ref.usd_fcfa)
    f = lambda n: f"{int(n):,}".replace(",", " ")   # noqa: E731 (séparateur de milliers français)
    rapport = bas / total if total else 0
    return {"reference_banque_mondiale_fcfa": [bas, haut], "message": (
        f"Coût modélisé : {f(total)} FCFA/t (collecte secondaire seule). Fourchette Banque mondiale (Afrique "
        f"subsaharienne, transport + exploitation) : {f(bas)} à {f(haut)} FCFA/t. Notre coût est environ "
        f"{rapport:.0f} fois plus bas : il exclut la pré-collecte, le CET, l'encadrement et les frais généraux, et "
        f"repose sur des salaires et des prix [H] à confirmer avec la mairie.")}
