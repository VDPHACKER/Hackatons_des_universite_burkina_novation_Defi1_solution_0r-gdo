"""Accès aux dépotoirs vérifiés (table `depotoir` de data/oregdo.db, produite par le module de vérification).

Schéma attendu : depotoir(id, lon REAL, lat REAL, statut TEXT, confiance REAL), statut dans
{verifie, a_confirmer, rejete}. Seuls les 'verifie' entrent dans le plan.
Repli : dépotoirs synthétiques (tant que la base ou la table n'existe pas) placés sur des îlots du pack.
"""
import logging
import sqlite3
from dataclasses import dataclass

import numpy as np

from ..config import COMMUNE_DEFAUT, RACINE
from ..geo import couche

journal = logging.getLogger("oregdo")
CHEMIN_BASE = RACINE / "data" / ("oregdo.db" if COMMUNE_DEFAUT == "ouaga" else f"oregdo_{COMMUNE_DEFAUT}.db")
CYCLE_STATUTS = ["verifie", "verifie", "a_confirmer", "rejete"]   # répartition des dépotoirs de démonstration


@dataclass(frozen=True)
class Depotoir:
    id: str
    lon: float
    lat: float
    statut: str
    confiance: float
    synthetique: bool = False


def synthetiques(n: int, graine: int, commune: str = COMMUNE_DEFAUT) -> list:
    """n dépotoirs de démonstration, statuts mélangés ; déterministes pour une graine donnée."""
    rng = np.random.default_rng(graine)
    ilots = couche("ilots", commune)
    choix = rng.choice(len(ilots), size=n, replace=False)
    sortie = []
    for k, i in enumerate(choix):
        c = ilots.geometry.iloc[int(i)].centroid
        sortie.append(Depotoir(f"SYN{k:03d}", c.x, c.y, CYCLE_STATUTS[k % len(CYCLE_STATUTS)],
                               round(float(rng.uniform(0.4, 0.95)), 2), True))
    return sortie


def lire_tous(chemin=None, graine: int = 0, n_synthetiques: int = 16) -> list:
    """Lit tous les dépotoirs ; base ou table absente, colonnes manquantes : repli synthétique."""
    chemin = chemin or CHEMIN_BASE
    try:
        if not chemin.exists():
            raise FileNotFoundError(str(chemin))
        con = sqlite3.connect(f"file:{chemin}?mode=ro", uri=True)
        try:
            lignes = con.execute("SELECT id, lon, lat, statut, confiance FROM depotoir").fetchall()
        finally:
            con.close()
        return [Depotoir(str(i), float(lo), float(la), str(s), float(c or 0)) for i, lo, la, s, c in lignes
                if lo is not None and la is not None]
    except (sqlite3.Error, OSError) as e:
        journal.warning("Base des dépotoirs indisponible (%s) : repli sur des dépotoirs synthétiques.", e)
        return synthetiques(n_synthetiques, graine)


def verifies(chemin=None, graine: int = 0) -> list:
    """Uniquement les dépotoirs au statut 'verifie' (règle d'intégrité du contrat)."""
    return [d for d in lire_tous(chemin, graine) if d.statut == "verifie"]
