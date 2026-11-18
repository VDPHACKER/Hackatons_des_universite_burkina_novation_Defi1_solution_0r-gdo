"""Valorisation : des ménages trient et revendent plastiques, métaux et papier-carton. Ces matières ne passent plus par la collecte.

Tout est hypothèse [H] (packs/<commune>/commune_config.yaml, section `valorisation`) : à confirmer avec les filières de recyclage de la commune.
Avec taux_tri = 0 (valeur par défaut), le moteur se comporte exactement comme avant.
"""
from ..config import COMMUNE_DEFAUT, charger_config


def part_detournee(sc, commune: str = COMMUNE_DEFAUT) -> float:
    """Part du poids total des déchets qui est triée puis revendue (0 à part_valorisable x captation)."""
    v = charger_config(commune).valorisation
    return max(0.0, min(1.0, sc.taux_tri)) * v.part_valorisable * v.captation


def facteur_collecte(sc, commune: str = COMMUNE_DEFAUT) -> float:
    """Multiplicateur de la production qui doit encore être collectée (1 = rien n'est trié)."""
    return 1.0 - part_detournee(sc, commune)


def recettes_j_fcfa(kg_valorises: float, commune: str = COMMUNE_DEFAUT) -> dict:
    """Recettes quotidiennes de la revente, partagées entre les ménages et les pré-collecteurs."""
    v = charger_config(commune).valorisation
    total = kg_valorises * v.prix_fcfa_kg
    menages = total * v.part_revenu_menage
    return {"menages": round(menages), "precollecteurs": round(total - menages), "total": round(total)}
