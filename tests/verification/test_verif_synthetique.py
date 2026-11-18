"""Tests du jeu synthétique : reproductibilité, détection des pièges, performance."""
import time

import pytest

from oregdo.verification import base, synthetique


@pytest.fixture(scope="module")
def resultat(tmp_path_factory, cfg):
    conn = base.ouvrir(tmp_path_factory.mktemp("s") / "s.db")
    t = time.perf_counter()
    bilan = synthetique.peupler(conn, cfg)
    return conn, bilan, time.perf_counter() - t


def test_jeu_reproductible():
    from datetime import datetime, timezone
    now = datetime(2026, 11, 16, tzinfo=timezone.utc)
    a, b = synthetique.generer(maintenant=now), synthetique.generer(maintenant=now)
    assert [(x["cas"], x["sig"]) for x in a] == [(x["cas"], x["sig"]) for x in b]
    assert [x["photos"] for x in a] == [x["photos"] for x in b]
    assert len(a) >= 250


def test_pieges_attrapes_et_bons_acceptes(resultat):
    conn, bilan, _ = resultat
    assert bilan["ecarts_avec_attendu"] <= 2        # tolérance : quelques bons peuvent finir « à confirmer »
    s = bilan["par_statut"]
    assert s["verifie"] > 100 and s["rejete"] > 80 and s.get("a_confirmer", 0) + s["rejete"] > 100
    assert bilan["depotoirs"] >= 40


def test_tout_est_etiquete_synthetique_et_rien_n_est_supprime(resultat):
    conn, bilan, _ = resultat
    assert conn.execute("SELECT COUNT(*) FROM signalement WHERE synthetique=0").fetchone()[0] == 0
    assert conn.execute("SELECT COUNT(*) FROM signalement").fetchone()[0] >= bilan["signalements_application"]
    assert conn.execute("SELECT COUNT(*) FROM ligne_refusee").fetchone()[0] >= 3


def test_gonflage_ne_gonfle_pas_les_depotoirs(resultat):
    conn, _, _ = resultat
    rows = conn.execute("SELECT nb_signalements, nb_enqueteurs FROM depotoir WHERE statut='verifie'").fetchall()
    assert all(r["nb_enqueteurs"] <= r["nb_signalements"] for r in rows)
    assert conn.execute("SELECT COUNT(*) FROM signalement WHERE appareil LIKE 'APP-GONFLE%' AND statut='verifie'").fetchone()[0] <= 6


def test_performance_300_signalements(resultat):
    _, bilan, total = resultat
    print(f"\n[perf] {bilan['signalements_application']} signalements d'application en {bilan['temps_application_s']} s ; total import compris {total:.2f} s")
    assert bilan["temps_application_s"] < 5
