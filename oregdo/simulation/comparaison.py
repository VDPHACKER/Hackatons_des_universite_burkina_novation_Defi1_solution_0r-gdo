"""Comparateur de scénarios : plan cible (valeurs du config) contre scénario modifié.

Les recettes d'abonnement (pré-collecteurs) et d'amendes ne sont pas des gains de la mairie : verdict neutre.
"""
from ..config import COMMUNE_DEFAUT, charger_config
from ..planning import depotoirs as acces_depotoirs
from ..planning.scenario import Scenario
from .modele import simuler

# Sens favorable de chaque indicateur final : +1 plus haut = mieux, -1 plus bas = mieux, 0 neutre.
SENS = {
    "tonnes_produites_totales": 0, "tonnes_collectees_totales": 1, "tonnes_fuite_totales": -1,
    "taux_couverture_moyen": 1, "depotoirs_actifs_fin": -1, "cout_par_tonne_fcfa": -1,
    "budget_consomme_fcfa": -1, "recettes_abonnement_fcfa": 0, "recettes_amendes_fcfa": 0,
    "stock_depotoirs_fin_tonnes": -1, "depotoirs_a_risque_inondation_saison_pluies": -1,
    "tonnes_caniveau_totales": -1, "tonnes_brulees_totales": 0, "nb_sanctions": 0,
}


_CACHE: dict = {}
_CACHE_MAX = 8


def _signature_sources() -> tuple:
    """Empreinte des sources qui changent le résultat : fichier de config du pack et base des dépotoirs."""
    def etat(chemin):
        try:
            st = chemin.stat()
            return (st.st_mtime_ns, st.st_size)
        except OSError:
            return None
    cfg = charger_config(COMMUNE_DEFAUT)
    return (etat(cfg.dossier_pack / "commune_config.yaml"), etat(acces_depotoirs.CHEMIN_BASE))


def simuler_avec_cache(sc: Scenario, jours: int | None, graine: int | None) -> dict:
    """Simulation mémorisée (clé : scénario, durée, graine, sources). Invalidée si le config ou la base changent."""
    cle = (repr(sorted(sc.to_dict().items())), jours, graine, _signature_sources())
    if cle not in _CACHE:
        if len(_CACHE) >= _CACHE_MAX:
            _CACHE.pop(next(iter(_CACHE)))
        _CACHE[cle] = simuler(sc, jours, graine)
    return _CACHE[cle]


def vider_cache() -> None:
    _CACHE.clear()


def comparer(reference: Scenario, modifie: Scenario, jours: int | None = None, graine: int | None = None) -> dict:
    """Simule les deux scénarios avec la même graine ; renvoie séries et tableau d'écarts."""
    a, b = simuler_avec_cache(reference, jours, graine), simuler_avec_cache(modifie, jours, graine)
    tableau = []
    for cle, sens in SENS.items():
        va, vb = a["final"][cle], b["final"][cle]
        ecart = None if va is None or vb is None else round(vb - va, 4)
        verdict = "neutre" if not sens or not ecart else ("meilleur" if ecart * sens > 0 else "moins bon")
        tableau.append({"indicateur": cle, "reference": va, "scenario": vb, "ecart": ecart,
                        "relatif": round(ecart / va, 4) if ecart is not None and va else None, "verdict": verdict})
    return {"jours": a["jours"], "graine": a["graine"],
            "reference": a, "plan_cible": a,        # « reference » est conservé comme alias de « plan_cible »
            "description_plan_cible": a["description"],
            "scenario": b, "indicateurs": tableau,
            "diagnostic": b["diagnostic"], "diagnostic_plan_cible": a["diagnostic"],
            "scenario_parametres": modifie.to_dict(), "reference_parametres": reference.to_dict()}
