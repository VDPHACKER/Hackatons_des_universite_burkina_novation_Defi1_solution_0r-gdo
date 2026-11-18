"""Plan de gestion d'un arrondissement : le plan communal découpé par arrondissement.

Rattachement : un îlot appartient au secteur qui le contient, un secteur à un arrondissement (packs/<commune>/secteurs.geojson).
Un point de regroupement (PR) est rattaché à l'arrondissement où vit la plus grande part de la population qu'il dessert ;
un dépotoir, à l'arrondissement dont le polygone le contient ; un voyage, à tous les arrondissements dont il visite un arrêt.
Les contours sont SYNTHÉTIQUES tant que les limites officielles ne sont pas fournies : le résultat le dit.
"""
import json
from functools import lru_cache

import numpy as np
from shapely.geometry import Point, mapping, shape
from shapely.ops import unary_union

from ..config import COMMUNE_DEFAUT, charger_config
from . import valorisation
from .parametres import moteur

AVERTISSEMENT = ("Découpage en arrondissements synthétique : à remplacer par les limites officielles. "
                 "Les indicateurs sont des estimations de planification, pas des mesures.")


@lru_cache(maxsize=2)
def _secteurs(commune: str):
    cfg = charger_config(commune)
    brut = json.loads((cfg.dossier_pack / "secteurs.geojson").read_text(encoding="utf-8"))
    sec2arr, par_arr = {}, {}
    for f in brut["features"]:
        p = f["properties"]
        sec2arr[p["id"]] = p["arrondissement"]
        par_arr.setdefault(p["arrondissement"], []).append((p["id"], p.get("nom", p["id"]), shape(f["geometry"])))
    union = {a: unary_union([g for _, _, g in l]) for a, l in par_arr.items()}
    return sec2arr, par_arr, union


def codes(commune: str = COMMUNE_DEFAUT) -> list:
    return sorted(_secteurs(commune)[1])


def _nom(code: str) -> str:
    return f"Arrondissement {int(code[1:])}"


def _calculer(detail: dict, sc, commune: str) -> dict:
    cfg = charger_config(commune)
    sec2arr, par_arr, union = _secteurs(commune)
    d, pr, t, dep = detail["donnees"], detail["pr"], detail["tournees"], detail["depotoirs"]
    arr_ilot = np.array([sec2arr.get(s, "") for s in d.ilots_secteur], dtype=object)
    pop = d.ilots_pop * sc.facteur_population
    prod_kg = cfg.demographie.production_kg_hab_jour
    f_collecte = valorisation.facteur_collecte(sc, commune)
    part_pr = sc.taux_abonnement + (1 - sc.taux_abonnement) * moteur(cfg).apport_volontaire_non_abonnes
    # PR -> arrondissement
    arr_pr = {}
    for k, j in enumerate(pr.retenus):
        servis = pr.affectation == j
        poids = {}
        for a, p in zip(arr_ilot[servis], pop[servis]):
            if a:
                poids[a] = poids.get(a, 0.0) + float(p)
        arr_pr[d.sites_ids[j]] = max(poids, key=poids.get) if poids else (arr_ilot[np.argmin(np.linalg.norm(d.ilots_xy - d.sites_xy[j], axis=1))] or None)
    # dépotoirs -> arrondissement
    arr_dep = {}
    for x in dep:
        p = Point(x.lon, x.lat)
        arr_dep[x.id] = next((a for a, g in union.items() if g.contains(p)), None)
    # voyages -> arrondissements visités
    arr_voyage = []
    for v in t.voyages:
        visites = {arr_pr.get(s["id"]) if s["type"] == "pr" else arr_dep.get(s["id"]) for s in v["arrets"]}
        arr_voyage.append({a for a in visites if a})
    sortie = {}
    for a in codes(commune):
        m = arr_ilot == a
        pop_a = float(pop[m].sum())
        servie = float(pop[m & (pr.affectation >= 0)].sum()) * part_pr
        ids_pr = [i for i, x in arr_pr.items() if x == a]
        charge = sum(float(pr.charge_kg_j[k]) for k, j in enumerate(pr.retenus) if d.sites_ids[j] in ids_pr)
        capacite = sum(float(d.sites_cap_kg_j[j]) for j in pr.retenus if d.sites_ids[j] in ids_pr)
        cout = sum(float(d.sites_cout[j]) for j in pr.retenus if d.sites_ids[j] in ids_pr)
        produit = pop_a * prod_kg
        a_collecter = produit * f_collecte
        voy = [i for i, s in enumerate(arr_voyage) if a in s]
        sortie[a] = {
            "code": a, "nom": _nom(a), "secteurs": [s for s, _, _ in par_arr[a]], "nb_secteurs": len(par_arr[a]),
            "population": round(pop_a), "nb_ilots": int(m.sum()),
            "tonnes_produites_j": round(produit / 1000, 1), "tonnes_a_collecter_j": round(a_collecter / 1000, 1),
            "tonnes_valorisees_j": round((produit - a_collecter) / 1000, 1),
            "couverture_population": round(min(servie / pop_a, 1.0), 4) if pop_a else 0.0,
            "nb_pr": len(ids_pr), "charge_pr_t_j": round(charge / 1000, 1), "capacite_pr_t_j": round(capacite / 1000, 1),
            "cout_installation_pr_fcfa": round(cout),
            "ecart_non_desservi_t_j": round(max(a_collecter - charge, 0) / 1000, 1),
            "nb_depotoirs_verifies": sum(1 for v in arr_dep.values() if v == a),
            "nb_voyages": len(voy), "distance_voyages_km": round(sum(t.voyages[i]["distance_m"] for i in voy) / 1000, 1),
            "_pr": ids_pr, "_voyages": voy,
        }
    return sortie


def tableau(detail: dict, sc, commune: str = COMMUNE_DEFAUT) -> dict:
    """Les arrondissements côte à côte, du moins bien desservi au mieux desservi."""
    brut = _calculer(detail, sc, commune)
    lignes = [{k: v for k, v in x.items() if not k.startswith("_")} for x in brut.values()]
    lignes.sort(key=lambda x: x["couverture_population"])
    return {"synthetique": True, "avertissement": AVERTISSEMENT, "arrondissements": lignes}


def plan_arrondissement(detail: dict, sc, code: str, commune: str = COMMUNE_DEFAUT) -> dict:
    """Plan de gestion d'un arrondissement : indicateurs, contour, PR, dépotoirs vérifiés, tournées qui le traversent."""
    code = code.upper()
    if code not in codes(commune):
        raise ValueError(f"Arrondissement inconnu : « {code} ». Valeurs possibles : {', '.join(codes(commune))}.")
    brut = _calculer(detail, sc, commune)
    x = brut[code]
    plan = detail["plan"]
    sec2arr, par_arr, union = _secteurs(commune)
    ids = set(x["_pr"])
    fc_pr = {"type": "FeatureCollection", "features": [f for f in plan["pr"]["features"] if f["properties"]["id"] in ids]}
    voy = set(x["_voyages"])
    cles = {(detail["tournees"].voyages[i]["camion"], detail["tournees"].voyages[i]["voyage"]) for i in voy}
    fc_t = {"type": "FeatureCollection", "features": [f for f in plan["tournees"]["features"]
                                                       if (f["properties"]["camion"], f["properties"]["voyage"]) in cles]}
    g = union[code]
    fc_dep = {"type": "FeatureCollection", "features": [
        {"type": "Feature", "geometry": {"type": "Point", "coordinates": [dp.lon, dp.lat]}, "properties": {"id": dp.id, "synthetique": dp.synthetique}}
        for dp in detail["depotoirs"] if g.contains(Point(dp.lon, dp.lat))]}
    rang = sorted(brut.values(), key=lambda z: z["couverture_population"])
    x = {k: v for k, v in x.items() if not k.startswith("_")}
    x["rang_couverture"] = [z["code"] for z in rang].index(code) + 1          # 1 = le moins bien desservi
    return {"synthetique": True, "avertissement": AVERTISSEMENT, "arrondissement": x,
            "contour": {"type": "Feature", "geometry": mapping(g), "properties": {"code": code, "nom": x["nom"]}},
            "pr": fc_pr, "depotoirs": fc_dep, "tournees": fc_t, "scenario": plan["scenario"]}
