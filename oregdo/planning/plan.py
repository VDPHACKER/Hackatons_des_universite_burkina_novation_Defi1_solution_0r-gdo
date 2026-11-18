"""Orchestration : scénario -> PR -> tournées -> KPI et GeoJSON. C'est ce que le recalcul en direct appelle."""
import hashlib
import json
import time


from ..config import COMMUNE_DEFAUT, charger_config
from . import couts as modele_couts
from . import depotoirs as acces_depotoirs
from . import donnees, pmediane, reseau, tournees, valorisation
from .parametres import moteur
from .scenario import Scenario

COMMUNE = COMMUNE_DEFAUT
PLAN_CIBLE = ("Plan cible calculé pour ce scénario : ce n'est pas la situation actuelle de la mairie. Le nombre de "
              "camions, le budget et les capacités sont des hypothèses [H] à confirmer.")


def donnees_du_scenario(sc: Scenario, commune: str = COMMUNE):
    """Données de base + quartiers ajoutés par le scénario."""
    return donnees.avec_quartiers(donnees.charger(commune), sc.nouveaux_quartiers, commune)


def _pr_geojson(d, pr, sc, commune):
    pop = d.ilots_pop * sc.facteur_population
    lonlat = reseau.deprojeter(d.sites_xy[pr.retenus], commune) if len(pr.retenus) else []
    feats = []
    for k, j in enumerate(pr.retenus):
        servis = pr.affectation == j
        feats.append({"type": "Feature", "geometry": {"type": "Point", "coordinates": lonlat[k]},
                      "properties": {"id": d.sites_ids[j], "charge_kg_j": round(float(pr.charge_kg_j[k]), 1),
                                     "capacite_kg_j": float(d.sites_cap_kg_j[j]), "cout_fcfa": float(d.sites_cout[j]),
                                     "population_desservie": int(pop[servis].sum())}})
    return {"type": "FeatureCollection", "features": feats}


def _tournees_geojson(t):
    return {"type": "FeatureCollection", "features": [
        {"type": "Feature", "geometry": {"type": "LineString", "coordinates": v["coordonnees"]},
         "properties": {"camion": v["camion"], "voyage": v["voyage"], "distance_km": round(v["distance_m"] / 1000, 2),
                        "charge_kg": v["charge_kg"], "arrets": v["arrets"]}} for v in t.voyages]}


def calculer_plan(sc: Scenario, commune: str = COMMUNE, depotoirs=None) -> dict:
    """Calcule le plan complet. `depotoirs` : liste de Depotoir (par défaut : les vérifiés de la base)."""
    return calculer_plan_detaille(sc, commune, depotoirs)["plan"]


def calculer_plan_detaille(sc: Scenario, commune: str = COMMUNE, depotoirs=None) -> dict:
    """Comme calculer_plan, mais renvoie aussi les objets internes (données, PR, tournées) utiles à la simulation."""
    debut = time.perf_counter()
    sc.valider(commune)
    cfg = charger_config(commune)
    limite = cfg.planification.limites.temps_calcul_max_s

    def garde(etape: str):
        """Garde-fou de durée globale : on abandonne entre deux étapes si le calcul dure trop (les solveurs ont aussi leur limite)."""
        if time.perf_counter() - debut > limite:
            raise ValueError(f"Calcul interrompu après l'étape « {etape} » : durée maximale de {limite} s dépassée. "
                             "Réduisez la taille du scénario (flotte, quartiers).")

    d = donnees_du_scenario(sc, commune)
    garde("données")
    pr = pmediane.resoudre(d, sc, commune)
    garde("localisation des PR")
    dep = acces_depotoirs.verifies(graine=cfg.simulation.graine) if depotoirs is None else \
        [x for x in depotoirs if x.statut == "verifie"]            # garde-fou : jamais d'autre statut
    t = tournees.calculer(d, pr, dep, sc, commune)
    freq = sc.frequence_collecte_jours
    produit = float(d.ilots_pop.sum() * sc.facteur_population * cfg.demographie.production_kg_hab_jour)
    valorise = produit * valorisation.part_detournee(sc, commune)      # triés et revendus par les ménages : ne passent pas par la collecte
    a_collecter = produit - valorise
    evacue = (t.kg_collectes - t.kg_depotoirs_collectes) / freq
    pop_totale = float(d.ilots_pop.sum() * sc.facteur_population)
    # Part des ménages dont les déchets passent par un PR : abonnés + non-abonnés qui apportent, dans les îlots servis.
    part_pr = sc.taux_abonnement + (1 - sc.taux_abonnement) * moteur(cfg).apport_volontaire_non_abonnes
    pop_servie = float((d.ilots_pop * sc.facteur_population)[pr.affectation >= 0].sum()) * part_pr
    kpi = {
        "tonnes_produites_j": round(produit / 1000, 1), "tonnes_evacuees_j": round(evacue / 1000, 1),
        "tonnes_non_evacuees_j": round(max(a_collecter - evacue, 0) / 1000, 1),
        # Fuite = part des déchets non évacués qui finit en dépôt sauvage (RGPH : tas + rue / non-abonnés = 0,59).
        "tonnes_fuite_j": round(max(a_collecter - evacue, 0) * cfg.simulation.fuite_vers_depotoir_si_pr_inaccessible / 1000, 1),
        "taux_fuite": round(max(a_collecter - evacue, 0) * cfg.simulation.fuite_vers_depotoir_si_pr_inaccessible / produit, 4) if produit else 0.0,
        "tonnes_valorisees_j": round(valorise / 1000, 1), "recettes_valorisation_j_fcfa": valorisation.recettes_j_fcfa(valorise, commune),
        "tonnes_depotoirs_enlevees": round(t.kg_depotoirs_collectes / 1000, 1),
        "couverture_pr": round(pr.couverture, 4),
        "taux_couverture_production": round(min((evacue + valorise) / produit, 1.0), 4) if produit else 0.0, "couverture_population": round(pop_servie / pop_totale, 4),
        "nb_pr": int(len(pr.retenus)), "nb_depotoirs_verifies": len(dep),
        "depotoirs_non_servis": sum(1 for n in t.non_servis if n["type"] == "depotoir"),
        "camions_utilises": len({v["camion"] for v in t.voyages}), "camions_disponibles": len(sc.camions_disponibles()),
        "distance_km": round(t.distance_effective_m / 1000, 1), "cout_collecte_fcfa": round(t.cout_fcfa),
        "cout_investissement_pr_fcfa": round(pr.cout_fcfa), "budget_pr_fcfa": sc.budget_pr_fcfa,
        "statut_pmediane": pr.statut,
    }
    camions_utilises = kpi["camions_utilises"]
    comp = modele_couts.composantes(sc, camions_utilises, t.distance_effective_m, pr.cout_fcfa, commune)
    detail = modele_couts.detail_par_tonne(comp, t.kg_collectes / 1000, freq, commune)
    kpi["cout_par_tonne_detail"] = detail                 # carburant, personnel, véhicules, PR, total + comparaison Banque mondiale
    kpi["cout_par_tonne_fcfa"] = detail["total_fcfa"]     # coût COMPLET (le carburant seul est dans cout_par_tonne_detail.carburant)
    kpi["depenses_mairie_j_fcfa"] = {                     # dépenses de la mairie pour une journée de tournées
        "carburant": round(comp["carburant_tournee"]), "personnel": round(comp["personnel_tournee"]),
        "vehicules": round(comp["vehicules_amortissement_jour"] + comp["vehicules_entretien_jour"]),
        "pr": round(comp["pr_jour"])}
    kpi["depenses_mairie_j_fcfa"]["total"] = sum(kpi["depenses_mairie_j_fcfa"].values())
    plan = {"nature": "plan_cible", "description": PLAN_CIBLE, "scenario": sc.to_dict(), "pr": _pr_geojson(d, pr, sc, commune), "tournees": _tournees_geojson(t),
            "non_servis": t.non_servis, "kpi": kpi}
    plan["empreinte"] = empreinte(plan)
    plan["temps_calcul_s"] = round(time.perf_counter() - debut, 3)
    return {"plan": plan, "couts": comp, "donnees": d, "pr": pr, "tournees": t, "depotoirs": dep}


def empreinte(plan: dict) -> str:
    """Signature du contenu décisionnel (PR + tournées + dépotoirs servis), pour vérifier qu'un plan n'a pas bougé."""
    cle = {"pr": sorted(f["properties"]["id"] for f in plan["pr"]["features"]),
           "tournees": [[f["properties"]["camion"], f["properties"]["voyage"], [a["id"] for a in f["properties"]["arrets"]]]
                        for f in plan["tournees"]["features"]]}
    return hashlib.sha1(json.dumps(cle, sort_keys=True).encode()).hexdigest()[:12]
