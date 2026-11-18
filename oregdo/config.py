"""Chargement de la configuration du pack commune (aucune valeur codée en dur ailleurs)."""
import os
from functools import lru_cache
from pathlib import Path
from types import SimpleNamespace

import yaml

RACINE = Path(__file__).resolve().parent.parent
# Commune servie par défaut : variable OREGDO_COMMUNE (un pack dans packs/<code>), « ouaga » si elle est absente.
COMMUNE_DEFAUT = os.environ.get("OREGDO_COMMUNE", "ouaga")


def _en_objet(valeur):
    """Transforme récursivement les dictionnaires en objets à attributs (cfg.verification.seuils.verifie)."""
    if isinstance(valeur, dict):
        return SimpleNamespace(**{k: _en_objet(v) for k, v in valeur.items()})
    return valeur


@lru_cache(maxsize=4)
def charger_config(commune: str = COMMUNE_DEFAUT, racine: Path = RACINE):
    """Lit packs/<commune>/commune_config.yaml. Renvoie un objet à attributs et garde le dictionnaire brut dans `.brut`."""
    chemin = Path(racine) / "packs" / commune / "commune_config.yaml"
    if not chemin.exists():
        raise FileNotFoundError(f"Configuration introuvable : {chemin}")
    brut = yaml.safe_load(chemin.read_text(encoding="utf-8"))
    cfg = _en_objet(brut)
    cfg.brut = brut
    cfg.dossier_pack = chemin.parent
    return cfg
