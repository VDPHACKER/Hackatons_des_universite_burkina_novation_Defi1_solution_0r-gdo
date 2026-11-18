"""Tournées de collecte : CVRP à voyages multiples. Solveur PyVRP par défaut (voir `_tournees_pyvrp`), OR-Tools en secours.

Choix de modélisation :
- un « véhicule » = un voyage d'un camion ; un camion fait au plus `voyages_max_par_jour` voyages ;
  le 1er voyage part du dépôt, les suivants du CET (retour de vidage) ; tous finissent au CET ;
- camions en panne : absents de la liste des véhicules (donc impossibles à retrouver dans les tournées) ;
- un PR dont la charge dépasse la capacité d'un camion est découpé en plusieurs arrêts ;
- chaque arrêt est facultatif avec une pénalité de non-visite ; les dépotoirs vérifiés pèsent plus (priorité) ;
- longueur maximale d'un voyage = vitesse x durée de journée / voyages (borne de temps de travail).
"""
from dataclasses import dataclass, field

import numpy as np
import shapely
from ortools.constraint_solver import pywrapcp, routing_enums_pb2

from ..config import COMMUNE_DEFAUT, charger_config
from . import graphe_routier, reseau
from .donnees import Donnees
from .donnees import charger as donnees_de_base
from .parametres import moteur
from .pmediane import ResultatPR
from .scenario import Scenario


@dataclass
class ResultatTournees:
    voyages: list = field(default_factory=list)       # dicts : camion, voyage, arrets, distance_m, charge_kg, coordonnees
    non_servis: list = field(default_factory=list)    # dicts : id, type, kg, motif
    kg_collectes: float = 0.0
    kg_depotoirs_collectes: float = 0.0
    distance_effective_m: float = 0.0
    cout_fcfa: float = 0.0


def _arrets(d: Donnees, pr: ResultatPR, depotoirs: list, sc: Scenario, commune: str):
    """Liste des arrêts candidats : (type, id, xy, kg, profil) ; PR découpés selon la capacité des camions."""
    mot = moteur(charger_config(commune))
    arrets, inaccessibles = [], []
    acc_pr = reseau.est_accessible({k: v[pr.retenus] for k, v in d.sites_profil.items()}, sc.saison_pluies, commune)
    for k, (j, kg) in enumerate(zip(pr.retenus, pr.charge_kg_j)):
        kg = float(kg) * sc.frequence_collecte_jours      # stock accumulé entre deux passages
        if not acc_pr[k]:
            inaccessibles.append({"id": d.sites_ids[j], "type": "pr", "kg": kg, "motif": "zone inondable (saison des pluies)"})
            continue
        morceaux = int(np.ceil(kg / sc.capacite_camion_kg)) if sc.capacite_camion_kg > 0 else 0
        for m in range(morceaux):
            part = min(sc.capacite_camion_kg, kg - m * sc.capacite_camion_kg)
            arrets.append(("pr", d.sites_ids[j], d.sites_xy[j], part, {c: v[j] for c, v in d.sites_profil.items()}))
    if depotoirs:
        xy = reseau.projeter([x.lon for x in depotoirs], [x.lat for x in depotoirs], commune)
        prof = reseau.profil_geometrique(xy, commune)
        acc = reseau.est_accessible(prof, sc.saison_pluies, commune)
        for i, x in enumerate(depotoirs):
            kg = float(min(mot.stock_depotoir_kg, sc.capacite_camion_kg))
            if acc[i]:
                arrets.append(("depotoir", x.id, xy[i], kg, {c: v[i] for c, v in prof.items()}))
            else:
                inaccessibles.append({"id": x.id, "type": "depotoir", "kg": kg, "motif": "zone inondable (saison des pluies)"})
    return arrets, inaccessibles


def _tournees_pyvrp(M, xy, arrets, voyages, max_voyage, sc, cfg, mot):
    """Solveur PyVRP (MIT, https://github.com/PyVRP/PyVRP) : recherche génétique hybride, nettement meilleure qu'une descente
    gloutonne (mesuré sur 298 arrêts : 13,7 % de distance en moins, même tonnage collecté).
    Même problème qu'OR-Tools : deux dépôts (camions, CET), voyages indépendants, arrêts facultatifs avec prime, capacité et
    longueur maximale de voyage. Arrêt sur un nombre d'itérations (déterministe) ; le temps n'est qu'un garde-fou.
    Renvoie {indice de voyage: nœuds [départ, arrêts..., CET]}, ou None (PyVRP absent, ou pas de solution faisable)."""
    try:
        from pyvrp import Client, Depot, Location, ProblemData, VehicleType
        from pyvrp.solve import solve
        from pyvrp.stop import MaxIterations, MaxRuntime, MultipleCriteria
    except ImportError:
        return None
    n0 = sum(1 for _, v in voyages if v == 0)
    n1 = len(voyages) - n0
    lieux = [Location(x=float(p[0]), y=float(p[1])) for p in xy]
    clients = []
    for k, a in enumerate(arrets, start=2):
        poids = mot.priorite_depotoir if a[0] == "depotoir" else 1.0
        # La prime vaut la pénalité d'OR-Tools multipliée par `facteur_service_pyvrp` : sans cela, le solveur « économise » de
        # la distance en abandonnant quelques arrêts (mesuré : 8 PR laissés de côté pour 6 % de distance gagnée).
        prime = (int(poids * a[3] / 1000 * mot.penalite_pr_m_par_tonne) + 1) * int(mot.facteur_service_pyvrp)
        clients.append(Client(location=k, pickup=[int(round(a[3]))], required=False, prize=prime))
    capacite = [int(sc.capacite_camion_kg)]
    types = [VehicleType(num_available=n0, capacity=capacite, start_depot=0, end_depot=1, max_distance=max_voyage)]
    if n1:
        types.append(VehicleType(num_available=n1, capacity=capacite, start_depot=1, end_depot=1, max_distance=max_voyage))
    distances = np.ascontiguousarray(M, dtype=np.int64)        # la matrice est passée telle quelle : pas de boucle sur les arêtes
    donnees = ProblemData(locations=lieux, clients=clients, depots=[Depot(location=0), Depot(location=1)], vehicle_types=types,
                          distance_matrices=[distances], duration_matrices=[np.zeros_like(distances)])
    arret = MultipleCriteria([MaxIterations(int(mot.pyvrp_iterations)), MaxRuntime(float(mot.pyvrp_temps_max_s))])
    sol = solve(donnees, stop=arret, seed=int(cfg.simulation.graine), display=False, collect_stats=False).best
    if not sol.is_feasible():
        return None
    libres = {0: [k for k, (_, v) in enumerate(voyages) if v == 0], 1: [k for k, (_, v) in enumerate(voyages) if v > 0]}
    routes = {}
    for rt in sol.routes():
        t = rt.vehicle_type()
        clients = [act.idx + 2 for act in rt.schedule() if act.is_client()]       # client i  <->  arrêt i  <->  nœud i + 2
        if clients:
            routes[libres[t].pop(0)] = [0 if t == 0 else 1] + clients + [1]
    return routes


def _coordonnees(xy, noeuds, chemins, commune):
    """[lon, lat] d'une tournée : le long des routes si le graphe est là, sinon en lignes droites entre les arrêts."""
    if chemins is None:
        return reseau.deprojeter(xy[noeuds], commune)
    morceaux = []
    for a, b in zip(noeuds[:-1], noeuds[1:]):
        seg = chemins.trace(a, b)
        morceaux.append(seg if not morceaux else seg[1:])
    ligne = shapely.LineString(np.vstack(morceaux)).simplify(3.0, preserve_topology=False)  # 3 m : invisible à l'écran, divise la taille du plan
    return reseau.deprojeter(np.asarray(ligne.coords), commune)


def _assembler(res, routes, voyages, M, xy, arrets, commune, cfg, chemins=None):
    """Construit le résultat (voyages, distance, tonnage, non servis, coût) à partir de routes {voyage: nœuds}."""
    kg = [0, 0] + [int(round(a[3])) for a in arrets]
    servis = set()
    if chemins is not None:                    # tous les trajets d'un coup, en parallèle
        chemins.tracer_tout([(a, b) for r in routes.values() for a, b in zip(r[:-1], r[1:])])
    for k in sorted(routes):
        camion, voy = voyages[k]
        noeuds = routes[k]
        visites = [n for n in noeuds if n >= 2]
        dist = int(sum(M[a, b] for a, b in zip(noeuds[:-1], noeuds[1:])))
        charge = sum(kg[n] for n in visites)
        servis.update(visites)
        res.voyages.append({
            "camion": camion, "voyage": voy, "distance_m": dist, "charge_kg": charge,
            "arrets": [{"id": arrets[n - 2][1], "type": arrets[n - 2][0], "kg": kg[n]} for n in visites],
            "coordonnees": _coordonnees(xy, noeuds, chemins, commune),
        })
        res.distance_effective_m += dist
        res.kg_collectes += charge
        res.kg_depotoirs_collectes += sum(kg[n] for n in visites if arrets[n - 2][0] == "depotoir")
    for n, a in enumerate(arrets, start=2):
        if n not in servis:
            res.non_servis.append({"id": a[1], "type": a[0], "kg": a[3], "motif": "capacité ou temps de tournée insuffisants"})
    res.cout_fcfa = res.distance_effective_m / 1000.0 * cfg.planification.camions.cout_km_fcfa
    return res


def calculer(d: Donnees, pr: ResultatPR, depotoirs: list, sc: Scenario, commune: str = COMMUNE_DEFAUT) -> ResultatTournees:
    cfg, res = charger_config(commune), ResultatTournees()
    mot = moteur(cfg)
    arrets, res.non_servis = _arrets(d, pr, depotoirs, sc, commune)
    camions = sc.camions_disponibles()
    if not arrets or not camions:
        res.non_servis += [{"id": a[1], "type": a[0], "kg": a[3], "motif": "aucun camion disponible"} for a in arrets] \
            if not camions else []
        return res
    # Nœuds : 0 = dépôt, 1 = CET, puis les arrêts.
    xy = np.vstack([d.depot_xy, d.cet_xy] + [a[2][None, :] for a in arrets])
    prof = {c: np.concatenate([d.depot_profil[c], d.cet_profil[c]] + [[a[4][c]] for a in arrets]) for c in d.depot_profil}
    graphe = graphe_routier.charger(commune)
    chemins = None
    if graphe is not None:
        # Distances réelles sur le réseau routier OSM. Les hubs (sites, dépôt, CET) sont précalculés ; les dépotoirs coûtent une ligne chacun.
        base = donnees_de_base(commune)          # hubs = points FIXES du pack (jamais les sites d'un nouveau quartier : le cache resterait valable)
        graphe.definir_hubs(np.vstack([base.sites_xy, base.depot_xy, base.cet_xy]))
        chemins = graphe.tournees(xy, sc.saison_pluies)
        M = np.rint(chemins.matrice).astype(int)
    else:                                  # repli : vol d'oiseau x facteur de détour
        M = np.rint(reseau.matrice_couts(xy, reseau.surcout_raccord(prof, sc.saison_pluies, commune),
                                         xy, reseau.surcout_raccord(prof, sc.saison_pluies, commune), commune)).astype(int)
    np.fill_diagonal(M, 0)
    # Un voyage dessert au moins un arrêt : inutile d'avoir plus de véhicules que d'arrêts (borne la mémoire et le
    # temps quand la flotte est énorme). Ordre « voyage d'abord » : chaque camion fait son 1er voyage avant un 2e.
    voyages = [(c, v) for v in range(sc.voyages_max_par_jour) for c in camions][: len(arrets)]
    starts = [0 if v == 0 else 1 for _, v in voyages]
    if str(mot.solveur_tournees).lower() == "pyvrp":
        max_voyage = int(mot.vitesse_kmh * 1000 * mot.duree_journee_h / sc.voyages_max_par_jour)
        routes = _tournees_pyvrp(M, xy, arrets, voyages, max_voyage, sc, cfg, mot)
        if routes is not None:
            return _assembler(res, routes, voyages, M, xy, arrets, commune, cfg, chemins)
        # PyVRP absent ou sans solution faisable : on continue avec OR-Tools (repli).
    gestionnaire = pywrapcp.RoutingIndexManager(len(xy), len(voyages), starts, [1] * len(voyages))
    modele = pywrapcp.RoutingModel(gestionnaire)
    # Matrices au niveau des index OR-Tools (sans rappel Python à chaque évaluation : 3 à 5 fois plus rapide).
    noeud_de = np.array([gestionnaire.IndexToNode(i) for i in range(gestionnaire.GetNumberOfIndices())])
    transit = modele.RegisterTransitMatrix(M[np.ix_(noeud_de, noeud_de)].tolist())
    modele.SetArcCostEvaluatorOfAllVehicles(transit)
    kg = [0, 0] + [int(round(a[3])) for a in arrets]
    dem = modele.RegisterUnaryTransitVector(np.array(kg)[noeud_de].tolist())
    modele.AddDimensionWithVehicleCapacity(dem, 0, [int(sc.capacite_camion_kg)] * len(voyages), True, "charge")
    max_voyage = int(mot.vitesse_kmh * 1000 * mot.duree_journee_h / sc.voyages_max_par_jour)
    modele.AddDimension(transit, 0, max_voyage, True, "distance")
    for n, a in enumerate(arrets, start=2):
        poids = mot.priorite_depotoir if a[0] == "depotoir" else 1.0
        modele.AddDisjunction([gestionnaire.NodeToIndex(n)], int(poids * a[3] / 1000 * mot.penalite_pr_m_par_tonne) + 1)
    p = pywrapcp.DefaultRoutingSearchParameters()
    p.first_solution_strategy = routing_enums_pb2.FirstSolutionStrategy.PATH_CHEAPEST_ARC
    p.local_search_metaheuristic = routing_enums_pb2.LocalSearchMetaheuristic.GREEDY_DESCENT
    p.solution_limit = int(mot.cvrp_solutions_max)
    p.time_limit.FromMilliseconds(int(mot.temps_cvrp_s * 1000))
    sol = modele.SolveWithParameters(p)
    if sol is None:
        res.non_servis += [{"id": a[1], "type": a[0], "kg": a[3], "motif": "aucune solution trouvée"} for a in arrets]
        return res
    servis = set()
    for k, (camion, voy) in enumerate(voyages):
        idx, noeuds = modele.Start(k), []
        while not modele.IsEnd(idx):
            noeuds.append(gestionnaire.IndexToNode(idx))
            idx = sol.Value(modele.NextVar(idx))
        noeuds.append(1)
        visites = [n for n in noeuds if n >= 2]
        if not visites:
            continue
        dist = int(sum(M[a, b] for a, b in zip(noeuds[:-1], noeuds[1:])))
        charge = sum(kg[n] for n in visites)
        servis.update(visites)
        res.voyages.append({
            "camion": camion, "voyage": voy, "distance_m": dist, "charge_kg": charge,
            "arrets": [{"id": arrets[n - 2][1], "type": arrets[n - 2][0], "kg": kg[n]} for n in visites],
            "coordonnees": _coordonnees(xy, noeuds, chemins, commune),
        })
        res.distance_effective_m += dist
        res.kg_collectes += charge
        res.kg_depotoirs_collectes += sum(kg[n] for n in visites if arrets[n - 2][0] == "depotoir")
    for n, a in enumerate(arrets, start=2):
        if n not in servis:
            res.non_servis.append({"id": a[1], "type": a[0], "kg": a[3], "motif": "capacité ou temps de tournée insuffisants"})
    res.cout_fcfa = res.distance_effective_m / 1000.0 * cfg.planification.camions.cout_km_fcfa
    return res
