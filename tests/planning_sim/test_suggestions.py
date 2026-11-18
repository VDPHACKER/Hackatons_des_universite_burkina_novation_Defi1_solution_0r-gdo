"""Tests des suggestions d'emplacements."""
from oregdo.planning import suggestions
from oregdo.planning.plan import calculer_plan
from oregdo.planning.scenario import Scenario


def test_suggestions_justifiees_et_disjointes_du_plan():
    sc = Scenario.depuis_config()
    s = suggestions.suggerer(sc, n=5)
    ids_plan = {f["properties"]["id"] for f in calculer_plan(sc)["pr"]["features"]}
    assert 0 < len(s["features"]) <= 5
    for f in s["features"]:
        p = f["properties"]
        assert p["id"] not in ids_plan
        assert p["population_gagnee"] > 0 and p["cout_fcfa"] > 0 and "habitants" in p["justification"]
    scores = [f["properties"]["cout_par_habitant_fcfa"] for f in s["features"]]
    assert scores[0] <= max(scores)
