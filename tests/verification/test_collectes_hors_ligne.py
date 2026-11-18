"""Collectes du pré-collecteur saisies hors ligne : un renvoi après coupure ne double jamais le poids."""
import sqlite3

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from oregdo import comptes, securite
from oregdo.api import plan, portails
from oregdo.verification import base

MDP = "mot-de-passe-test"


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setenv("OREGDO_DB", str(tmp_path / "collectes.db"))
    monkeypatch.setenv("OREGDO_AUTH", "1")
    securite.reinitialiser_limites()
    app = FastAPI()
    app.include_router(portails.router, prefix="/api")
    plan.reinitialiser()
    return TestClient(app)


def se_connecter(client, ident):
    conn = base.ouvrir()
    comptes.creer_utilisateur(conn, ident, ident.upper(), "precollecteur", MDP, "Secteur 12", "P-12")
    conn.close()
    r = client.post("/api/auth/connexion", json={"identifiant": ident, "mot_de_passe": MDP})
    return {"Authorization": "Bearer " + r.json()["jeton"]}


def test_un_renvoi_avec_la_meme_cle_ne_double_pas_la_collecte(client):
    h = se_connecter(client, "precol-a")
    corps = {"kg": 42.5, "nb_menages": 12, "cle_client": "c-2026-0001"}
    premiere = client.post("/api/precollecteur/collectes", json=corps, headers=h)
    assert premiere.status_code == 201 and "deja_enregistree" not in premiere.json()
    renvoi = client.post("/api/precollecteur/collectes", json=corps, headers=h)
    assert renvoi.status_code == 201 and renvoi.json()["deja_enregistree"] is True and renvoi.json()["id"] == premiere.json()["id"]
    liste = client.get("/api/precollecteur/collectes", headers=h).json()
    assert liste["totaux"]["nb_collectes"] == 1 and liste["totaux"]["kg"] == 42.5


def test_deux_collectes_sans_cle_ou_avec_des_cles_differentes_comptent_deux_fois(client):
    h = se_connecter(client, "precol-a")
    client.post("/api/precollecteur/collectes", json={"kg": 10}, headers=h)
    client.post("/api/precollecteur/collectes", json={"kg": 10}, headers=h)
    client.post("/api/precollecteur/collectes", json={"kg": 10, "cle_client": "cle-un-1"}, headers=h)
    client.post("/api/precollecteur/collectes", json={"kg": 10, "cle_client": "cle-deux-2"}, headers=h)
    assert client.get("/api/precollecteur/collectes", headers=h).json()["totaux"]["nb_collectes"] == 4


def test_la_meme_cle_chez_deux_pre_collecteurs_n_est_pas_un_doublon(client):
    a, b = se_connecter(client, "precol-a"), se_connecter(client, "precol-b")
    client.post("/api/precollecteur/collectes", json={"kg": 5, "cle_client": "meme-cle-1"}, headers=a)
    r = client.post("/api/precollecteur/collectes", json={"kg": 7, "cle_client": "meme-cle-1"}, headers=b)
    assert "deja_enregistree" not in r.json()
    assert client.get("/api/precollecteur/collectes", headers=b).json()["totaux"]["kg"] == 7


@pytest.mark.parametrize("cle", ["a b", "x" * 41, 12345, "é€"])
def test_une_cle_invalide_est_refusee_en_francais(client, cle):
    h = se_connecter(client, "precol-a")
    r = client.post("/api/precollecteur/collectes", json={"kg": 5, "cle_client": cle}, headers=h)
    assert r.status_code == 422 and "clé" in r.json()["detail"]


def test_une_ancienne_base_avec_collectes_est_migree_sans_perte(tmp_path):
    chemin = tmp_path / "ancienne.db"
    c = sqlite3.connect(chemin)
    c.execute("CREATE TABLE collecte (id INTEGER PRIMARY KEY AUTOINCREMENT, date TEXT NOT NULL, kg REAL NOT NULL, nb_menages INTEGER NOT NULL, "
              "point TEXT, utilisateur TEXT NOT NULL, saisi_le TEXT NOT NULL)")
    c.execute("INSERT INTO collecte (date, kg, nb_menages, point, utilisateur, saisi_le) VALUES ('2026-01-01', 30, 8, 'P-1', 'u1', '2026-01-01')")
    c.commit(); c.close()
    conn = base.ouvrir(chemin)
    assert "cle_client" in {r["name"] for r in conn.execute("PRAGMA table_info(collecte)")}
    assert tuple(conn.execute("SELECT COUNT(*), SUM(kg) FROM collecte").fetchone()) == (1, 30.0)
    conn.close()

