"""Suggestions d'emplacements de PR supplémentaires, justifiées par des chiffres (population, distance, coût)."""
import numpy as np

from ..config import COMMUNE_DEFAUT, charger_config
from . import pmediane, reseau, valorisation
from .plan import donnees_du_scenario
from .scenario import Scenario


def suggerer(sc: Scenario, n: int = 10, commune: str = COMMUNE_DEFAUT) -> dict:
    """Classe les sites candidats NON retenus par population non desservie gagnée par FCFA investi."""
    cfg = charger_config(commune)
    d = donnees_du_scenario(sc, commune)
    pr = pmediane.resoudre(d, sc, commune)
    non_servi = pr.affectation < 0
    pop = d.ilots_pop * sc.facteur_population
    ok = np.setdiff1d(np.flatnonzero(reseau.est_accessible(d.sites_profil, sc.saison_pluies, commune)), pr.retenus)
    cout = reseau.matrice_couts(
        d.ilots_xy[non_servi], reseau.surcout_raccord({k: v[non_servi] for k, v in d.ilots_profil.items()}, sc.saison_pluies, commune, inondable_seul=True),
        d.sites_xy[ok], reseau.surcout_raccord({k: v[ok] for k, v in d.sites_profil.items()}, sc.saison_pluies, commune, inondable_seul=True), commune,
        saison_pluies=sc.saison_pluies, acces=True, limite=sc.rayon_acces_pr_m)
    dans = cout <= sc.rayon_acces_pr_m
    pop_ns = pop[non_servi]
    gain = (dans * pop_ns[:, None]).sum(axis=0)
    # Une même population ne doit pas justifier deux sites voisins : sélection gloutonne.
    choisis, couverte = [], np.zeros(len(pop_ns), bool)
    prod, taux = cfg.demographie.production_kg_hab_jour * valorisation.facteur_collecte(sc, commune), sc.taux_abonnement
    for _ in range(min(n, len(ok))):
        g = ((dans & ~couverte[:, None]) * pop_ns[:, None]).sum(axis=0)
        score = g / d.sites_cout[ok]
        k = int(np.argmax(score))
        if g[k] <= 0:
            break
        choisis.append((k, g[k], float(cout[dans[:, k] & ~couverte, k].mean())))
        couverte |= dans[:, k]
    lonlat = reseau.deprojeter(d.sites_xy[ok[[c[0] for c in choisis]]], commune) if choisis else []
    feats = []
    for rang, ((k, g, dmoy), ll) in enumerate(zip(choisis, lonlat), start=1):
        j = ok[k]
        c = float(d.sites_cout[j])
        feats.append({"type": "Feature", "geometry": {"type": "Point", "coordinates": ll}, "properties": {
            "rang": rang, "id": d.sites_ids[j], "population_gagnee": int(g), "distance_moyenne_m": int(dmoy),
            "cout_fcfa": int(c), "cout_par_habitant_fcfa": round(c / g, 1),
            "tonnes_j_captees": round(g * prod * taux / 1000, 2), "capacite_kg_j": float(d.sites_cap_kg_j[j]),
            "justification": (f"Dessert {int(g)} habitants aujourd'hui non couverts, à {int(dmoy)} m en moyenne "
                              f"(rayon d'accès {int(sc.rayon_acces_pr_m)} m), pour {int(c):,} FCFA ".replace(",", " ")
                              + f"soit {c / g:.0f} FCFA par habitant.")}})
    return {"type": "FeatureCollection", "features": feats,
            "resume": {"population_non_desservie": int(pop_ns.sum()), "budget_pr_fcfa": sc.budget_pr_fcfa,
                       "cout_total_suggestions_fcfa": int(sum(f["properties"]["cout_fcfa"] for f in feats))}}
