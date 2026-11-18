"""Désactive le préchauffage en arrière-plan du routeur pendant les tests (il fausserait les chronométrages)."""
import os

os.environ["OREGDO_PRECHAUFFAGE"] = "0"
os.environ["OREGDO_AUTH"] = "0"   # l'authentification (module de vérification) est testée ailleurs ; ici on teste le calcul
# Les aléas « signalements piégés » écrivent dans la base de vérification : base temporaire pour ne pas polluer data/oregdo.db.
import tempfile
os.environ.setdefault("OREGDO_DB", os.path.join(tempfile.mkdtemp(prefix="oregdo_tests_"), "tests.db"))

import pytest


@pytest.fixture(autouse=True, scope="session")
def base_depotoirs_isolee(tmp_path_factory):
    """Les tests ne lisent jamais data/oregdo.db (écrite par le module de vérification) : repli synthétique déterministe."""
    from oregdo.planning import depotoirs
    ancien = depotoirs.CHEMIN_BASE
    depotoirs.CHEMIN_BASE = tmp_path_factory.mktemp("vide") / "absente.db"
    yield
    depotoirs.CHEMIN_BASE = ancien
