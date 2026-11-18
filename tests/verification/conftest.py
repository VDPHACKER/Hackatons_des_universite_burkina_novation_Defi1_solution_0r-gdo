"""Outils communs aux tests de vérification : configuration, couches et points de test."""
import random
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from oregdo.config import charger_config  # noqa: E402
from oregdo.verification import controles  # noqa: E402


@pytest.fixture(scope="session")
def cfg():
    return charger_config("ouaga")


@pytest.fixture(scope="session")
def ref():
    return controles.reference("ouaga")


@pytest.fixture(scope="session")
def bons_points(ref):
    """Points valides : dans la commune ET dans un secteur, hors eau et hors aéroport (graine fixe)."""
    from shapely.geometry import Point
    rng = random.Random(7)
    minx, miny, maxx, maxy = -1.60, 12.30, -1.45, 12.45
    pts = []
    while len(pts) < 60:
        lon, lat = rng.uniform(minx, maxx), rng.uniform(miny, maxy)
        s = ref.secteur_de(lat, lon)
        if s and not ref.eau.covers(Point(lon, lat)) and not ref.aeroport.covers(Point(lon, lat)):
            pts.append({"lat": lat, "lon": lon, "secteur": s[1]})
    return pts


@pytest.fixture
def sig(bons_points):
    """Un signalement correct, daté d'il y a une heure."""
    from datetime import datetime, timedelta, timezone
    p = bons_points[0]
    return {**p, "enqueteur": "E1", "appareil": "A1",
            "horodatage": (datetime.now(timezone.utc) - timedelta(hours=1)).isoformat()}


# L'authentification est testée explicitement (test_verif_securite.py) ; ailleurs on la coupe.
import os  # noqa: E402

os.environ["OREGDO_AUTH"] = "0"


@pytest.fixture(autouse=True)
def secteurs_officiels(cfg, monkeypatch, request):
    """Par défaut, les tests exercent le contrôle STRICT du secteur (couche officielle). Les tests marqués
    `secteurs_provisoires` utilisent le réglage réel du pack, où le secteur déclaré n'est pas contrôlé."""
    if "secteurs_provisoires" not in request.keywords:
        monkeypatch.setattr(cfg.verification, "secteurs_officiels", True, raising=False)
