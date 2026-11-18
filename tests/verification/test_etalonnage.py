"""Étalonnage du modèle sur les collectes saisies par les pré-collecteurs (mesure l'écart, ne modifie rien)."""
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from oregdo import comptes, securite
from oregdo.api import plan, portails
from oregdo.config import charger_config
from oregdo.planning import etalonnage
from oregdo.verification import base

MDP = "mot-de-passe-test"


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setenv("OREGDO_DB", str(tmp_path / "etalonnage.db"))
    monkeypatch.setenv("OREGDO_AUTH", "1")
    securite.reinitialiser_limites()
    app = FastAPI()
    app.include_router(portails.router, prefix="/api")
    plan.reinitialiser()
    return TestClient(app)


def kg_par_menage_modele():
    d = charger_config().demographie
    return d.production_kg_hab_jour * d.population / d.menages


def remplir(points, par_point, kg_par_menage, menages=20):
    conn = base.ouvrir()
    for p in range(points):
        for _ in range(par_point):
            conn.execute("INSERT INTO collecte (date, kg, nb_menages, point, utilisateur, saisi_le) VALUES ('2026-11-01', ?, ?, ?, 'u', '2026-11-01')",
                         (kg_par_menage * menages, menages, f"P-{p}"))
    conn.commit(); conn.close()


def test_sans_collecte_l_etalonnage_dit_qu_il_attend_des_donnees(client):
    conn = base.ouvrir()
    r = etalonnage.etalonner(conn); conn.close()
    assert r["collectes"] == 0 and r["suffisant"] is False and r["ecart_pct"] is None and "Aucune collecte" in r["avis"]


def test_trop_peu_de_mesures_ne_conclut_pas(client):
    remplir(1, 4, kg_par_menage_modele() * 2)                  # écart énorme, mais 4 collectes sur 1 seul point
    conn = base.ouvrir(); r = etalonnage.etalonner(conn); conn.close()
    assert r["suffisant"] is False and "Trop peu de mesures" in r["avis"] and "valeur_suggeree" not in r


def test_un_terrain_coherent_avec_le_modele_est_confirme(client):
    remplir(4, 4, kg_par_menage_modele() * 1.1)                 # +10 % : dans la tolérance de 20 %
    conn = base.ouvrir(); r = etalonnage.etalonner(conn); conn.close()
    assert r["suffisant"] is True and "cohérent" in r["avis"] and "valeur_suggeree" not in r and r["ecart_pct"] == pytest.approx(10, abs=0.6)


def test_un_ecart_durable_propose_une_valeur_sans_rien_modifier(client):
    avant = charger_config().demographie.production_kg_hab_jour
    remplir(4, 4, kg_par_menage_modele() * 1.5)                 # +50 %
    conn = base.ouvrir(); r = etalonnage.etalonner(conn); conn.close()
    assert r["suffisant"] is True and r["ecart_pct"] == pytest.approx(50, abs=0.6)
    assert r["valeur_suggeree"] == pytest.approx(avant * 1.5, rel=0.01) and "Relire le fichier" in r["avis"]
    assert charger_config().demographie.production_kg_hab_jour == avant           # aucun paramètre n'a été changé


def test_la_route_est_reservee_a_la_mairie(client):
    assert client.get("/api/calibrage").status_code == 401
    conn = base.ouvrir()
    comptes.creer_utilisateur(conn, "precol-x", "P", "precollecteur", MDP, None, None)
    comptes.creer_utilisateur(conn, "mairie-x", "M", "mairie", MDP, None, None)
    conn.close()

    def entetes(i):
        return {"Authorization": "Bearer " + client.post("/api/auth/connexion", json={"identifiant": i, "mot_de_passe": MDP}).json()["jeton"]}
    assert client.get("/api/calibrage", headers=entetes("precol-x")).status_code == 403
    r = client.get("/api/calibrage", headers=entetes("mairie-x"))
    assert r.status_code == 200 and {"collectes", "avis", "kg_par_menage_modele"} <= set(r.json())
