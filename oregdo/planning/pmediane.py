"""Localisation des points de regroupement (PR) : p-médiane capacitée sous budget et rayon d'accès.

Modèle (corrigé par rapport au PDF : il manquait budget et rayon, et le « p » fixe est remplacé par le budget) :
  variables  y_j in {0,1} (site ouvert), x_ij in [0,1] (part de la demande de l'îlot i servie par le site j),
             définies seulement si coût_effectif(i,j) <= rayon d'accès
  minimiser  somme_ij q_i * (d_ij - R) * x_ij        (équivaut à : distance pondérée + pénalité R par kg non servi)
  sous       somme_j x_ij <= 1 ; somme_i q_i x_ij <= cap_j y_j ; somme_j cout_j y_j <= budget
Solveur : HiGHS via scipy.optimize.milp (creux, limite de temps) : plus rapide que CBC sur ~15 000 variables.
"""
import hashlib
import threading
from dataclasses import dataclass

import numpy as np
from scipy.optimize import Bounds, LinearConstraint, milp
from scipy.sparse import coo_array, vstack

from ..config import COMMUNE_DEFAUT, charger_config
from . import reseau, valorisation
from .donnees import Donnees
from .parametres import moteur
from .scenario import Scenario


# Mémoire des solutions optimales : une panne de camion, une fréquence ou une flotte différente ne changent pas le problème
# de localisation des PR, donc le recalcul en direct réutilise la solution (clé = empreinte exacte du problème envoyé au solveur).
_CACHE: dict = {}
_CACHE_MAX = 16
_VERROU = threading.Lock()


def _empreinte_probleme(c, A, hauts, ns, limite) -> str:
    h = hashlib.blake2b(digest_size=16)
    for t in (c, A.data, A.indices, A.indptr, hauts, np.array([ns, limite], dtype=float)):
        h.update(np.ascontiguousarray(t).tobytes())
    return h.hexdigest()


@dataclass
class ResultatPR:
    retenus: np.ndarray        # indices des sites retenus (dans Donnees)
    charge_kg_j: np.ndarray    # charge servie par site retenu
    affectation: np.ndarray    # pour chaque îlot, indice du site (-1 si non servi)
    demande_kg_j: np.ndarray   # demande par îlot
    couverture: float          # part de la demande servie
    cout_fcfa: float
    distance_moy_m: float
    statut: str


def demande_ilots(d: Donnees, sc: Scenario, commune: str = COMMUNE_DEFAUT) -> np.ndarray:
    """Production quotidienne qui doit transiter par un PR (kg/jour) : celle des abonnés (pré-collecte) plus
    l'apport volontaire d'une part des non-abonnés (bacs à ordures, RGPH 2019)."""
    cfg = charger_config(commune)
    apport = moteur(cfg).apport_volontaire_non_abonnes
    part = sc.taux_abonnement + (1 - sc.taux_abonnement) * apport
    return d.ilots_pop * sc.facteur_population * cfg.demographie.production_kg_hab_jour * part * valorisation.facteur_collecte(sc, commune)


def resoudre(d: Donnees, sc: Scenario, commune: str = COMMUNE_DEFAUT) -> ResultatPR:
    mot = moteur(charger_config(commune))
    q = demande_ilots(d, sc, commune)
    R = sc.rayon_acces_pr_m
    # Sites accessibles aux camions : en saison des pluies on écarte ceux en zone inondable.
    ok = np.flatnonzero(reseau.est_accessible(d.sites_profil, sc.saison_pluies, commune))
    cout = reseau.matrice_couts(
        d.ilots_xy, reseau.surcout_raccord(d.ilots_profil, sc.saison_pluies, commune, inondable_seul=True),
        d.sites_xy[ok], reseau.surcout_raccord({k: v[ok] for k, v in d.sites_profil.items()}, sc.saison_pluies, commune, inondable_seul=True),
        commune, saison_pluies=sc.saison_pluies, acces=True, limite=R)     # graphe routier : accès d'un habitant, borné au rayon R
    ii, jj = np.nonzero(cout <= R)
    ns, np_ = len(ok), len(ii)
    vide = ResultatPR(np.array([], int), np.array([]), np.full(len(q), -1), q, 0.0, 0.0, 0.0, "aucun_site")
    if np_ == 0 or sc.budget_pr_fcfa <= 0:
        return vide
    qt = q / 1000.0   # tonnes, pour garder des coefficients raisonnables
    c = np.concatenate([np.zeros(ns), qt[ii] * (cout[ii, jj] - R)])
    cols_x = ns + np.arange(np_)
    a_ilot = coo_array((np.ones(np_), (ii, cols_x)), shape=(len(q), ns + np_))
    a_site = coo_array((np.concatenate([q[ii] / 1000.0, -d.sites_cap_kg_j[ok] / 1000.0]),
                        (np.concatenate([jj, np.arange(ns)]), np.concatenate([cols_x, np.arange(ns)]))),
                       shape=(ns, ns + np_))
    a_bud = coo_array((d.sites_cout[ok], (np.zeros(ns, int), np.arange(ns))), shape=(1, ns + np_))
    A = vstack([a_ilot, a_site, a_bud]).tocsr()
    hauts = np.concatenate([np.ones(len(q)), np.zeros(ns), [sc.budget_pr_fcfa]])
    cle = _empreinte_probleme(c, A, hauts, ns, mot.temps_milp_s)
    en_cache = _CACHE.get(cle)
    if en_cache is None:
        res = milp(c, constraints=LinearConstraint(A, -np.inf, hauts),
                   integrality=np.concatenate([np.ones(ns), np.zeros(np_)]),
                   bounds=Bounds(0, 1), options={"time_limit": mot.temps_milp_s, "mip_rel_gap": 0.01})
        en_cache = (None if res.x is None else res.x.copy(), res.status)
        if res.status == 0:                       # on ne mémorise qu'une solution optimale (pas une limite de temps atteinte)
            with _VERROU:
                if len(_CACHE) >= _CACHE_MAX:
                    _CACHE.pop(next(iter(_CACHE)))
                _CACHE[cle] = en_cache
    solution, statut_solveur = en_cache
    if solution is None:
        return vide
    x = solution[ns:]
    flux = np.zeros(ns)
    np.add.at(flux, jj, q[ii] * x)
    # Affectation de chaque îlot à son site principal (plus grande part servie).
    meilleur = np.zeros(len(q))
    aff = np.full(len(q), -1)
    for k in np.flatnonzero(x > 1e-6):
        if x[k] > meilleur[ii[k]]:
            meilleur[ii[k]], aff[ii[k]] = x[k], ok[jj[k]]
    ouverts = np.flatnonzero(flux > 1e-6)
    servie = float(np.sum(q[ii] * x))
    dist = float(np.sum(q[ii] * x * cout[ii, jj]) / servie) if servie > 0 else 0.0
    statut = "optimal" if statut_solveur == 0 else "meilleure_solution_trouvee"
    return ResultatPR(ok[ouverts], flux[ouverts], aff, q, servie / q.sum() if q.sum() > 0 else 0.0,
                      float(d.sites_cout[ok[ouverts]].sum()), dist, statut)
