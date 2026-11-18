"""Tests de la base SQLite : création, journal, revalidation, rien n'est supprimé."""
import pytest

from oregdo.verification import base


@pytest.fixture
def conn(tmp_path):
    return base.ouvrir(tmp_path / "t.db")


def test_creation_des_tables(conn):
    noms = {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    assert {"signalement", "depotoir", "journal", "photo", "ligne_refusee"} <= noms


def test_ajout_et_journal_automatique(conn):
    sid = base.ajouter_signalement(conn, {"lat": 12.3, "lon": -1.5}, 80, "verifie", [{"controle": "position"}], ["ff00"])
    s = base.lire_signalement(conn, sid)
    assert s["statut"] == "verifie" and s["motifs"][0]["controle"] == "position"
    assert base.empreintes_connues(conn) == [(sid, 0xFF00)]
    assert base.journal_du_signalement(conn, sid)[0]["agent"] == "automatique"


def test_revalidation_tracee(conn):
    sid = base.ajouter_signalement(conn, {"lat": 12.3, "lon": -1.5}, 50, "a_confirmer", [])
    s = base.revalider(conn, sid, "verifie", "Awa", "Confirmé sur place")
    assert s["statut"] == "verifie"
    j = base.journal_du_signalement(conn, sid)
    assert j[-1]["agent"] == "Awa" and j[-1]["ancien_statut"] == "a_confirmer"


def test_revalidation_invalide(conn):
    sid = base.ajouter_signalement(conn, {}, 10, "rejete", [])
    with pytest.raises(ValueError):
        base.revalider(conn, sid, "n_importe_quoi", "Awa", "x")
    with pytest.raises(ValueError):
        base.revalider(conn, sid, "verifie", "", "x")
    with pytest.raises(LookupError):
        base.revalider(conn, 999, "verifie", "Awa", "x")


def test_un_rejet_reste_en_base(conn):
    sid = base.ajouter_signalement(conn, {"lat": 0, "lon": 0}, 5, "rejete", [{"motif": "hors zone"}])
    assert [s["id"] for s in base.lister_signalements(conn, "rejete")] == [sid]
    assert base.compter_par_statut(conn) == {"rejete": 1}
