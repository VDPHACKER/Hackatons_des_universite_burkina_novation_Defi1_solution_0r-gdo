"""Centre de notifications (brigade, mairie) et historique de suivi du citoyen. Base temporaire, vrais comptes et jetons."""
import base64

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from oregdo import comptes, securite
from oregdo.api import notifications, plan, portails, signalements
from oregdo.planning import depotoirs
from oregdo.verification import base
from outils_photo import photo_neuve

MDP = "mot-de-passe-test"


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setenv("OREGDO_DB", str(tmp_path / "notif.db"))
    monkeypatch.setenv("OREGDO_AUTH", "1")
    monkeypatch.setattr(depotoirs, "CHEMIN_BASE", tmp_path / "notif.db")
    securite.reinitialiser_limites()
    app = FastAPI()
    for module in (signalements, plan, portails, notifications):
        app.include_router(module.router, prefix="/api")
    plan.reinitialiser()
    return TestClient(app)


def connecter(client, ident, role):
    conn = base.ouvrir()
    comptes.creer_utilisateur(conn, ident, ident.upper(), role, MDP, None, None)
    conn.close()
    r = client.post("/api/auth/connexion", json={"identifiant": ident, "mot_de_passe": MDP})
    assert r.status_code == 200, r.text
    return {"Authorization": "Bearer " + r.json()["jeton"]}


def deposer(client, sig, avec_photo=True):
    corps = {**sig, "photos": [base64.b64encode(photo_neuve()).decode()] if avec_photo else []}
    r = client.post("/api/signalements", json=corps)
    assert r.status_code == 201, r.text
    return r.json()


def test_un_signalement_verifie_notifie_la_mairie_pas_la_brigade(client, sig):
    mairie, brigade = connecter(client, "mairie1", "mairie"), connecter(client, "brigade1", "brigade")
    r = deposer(client, sig)
    assert r["statut"] == "verifie"
    m = client.get("/api/notifications", headers=mairie).json()
    assert m["non_lues"] == 1 and m["evenements"][0]["type"] == "verifie" and m["evenements"][0]["non_lu"] is True
    assert client.get("/api/notifications", headers=brigade).json()["non_lues"] == 0


def test_un_signalement_a_confirmer_notifie_la_brigade(client, sig):
    brigade = connecter(client, "brigade1", "brigade")
    r = deposer(client, sig, avec_photo=False)
    assert r["statut"] == "a_confirmer"
    b = client.get("/api/notifications", headers=brigade).json()
    assert b["non_lues"] == 1 and b["evenements"][0]["type"] == "a_verifier" and "attend la visite" in b["evenements"][0]["texte"]


def test_marquer_comme_lu_puis_nouvel_evenement(client, sig, bons_points):
    mairie = connecter(client, "mairie1", "mairie")
    deposer(client, sig)
    assert client.get("/api/notifications", headers=mairie).json()["non_lues"] == 1
    assert client.post("/api/notifications/lues", headers=mairie).json()["non_lues"] == 0
    apres = client.get("/api/notifications", headers=mairie).json()
    assert apres["non_lues"] == 0 and len(apres["evenements"]) == 1 and apres["evenements"][0]["non_lu"] is False   # l'événement reste consultable
    import time
    time.sleep(1.1)                                    # les dates ont la précision de la seconde
    autre = {**bons_points[5], "enqueteur": "E2", "appareil": "A2", "horodatage": sig["horodatage"]}
    deposer(client, autre)
    assert client.get("/api/notifications", headers=mairie).json()["non_lues"] == 1


def test_la_lecture_est_propre_a_chaque_compte(client, sig):
    m1, m2 = connecter(client, "mairie1", "mairie"), connecter(client, "mairie2", "mairie")
    deposer(client, sig)
    client.post("/api/notifications/lues", headers=m1)
    assert client.get("/api/notifications", headers=m1).json()["non_lues"] == 0
    assert client.get("/api/notifications", headers=m2).json()["non_lues"] == 1


def test_les_donnees_de_demonstration_ne_notifient_personne(client, sig):
    mairie = connecter(client, "mairie1", "mairie")
    conn = base.ouvrir()
    conn.execute("INSERT INTO signalement (lat, lon, recu_le, statut, score, synthetique) VALUES (12.37, -1.52, '2999-01-01T00:00:00+00:00', 'verifie', 90, 1)")
    conn.execute("INSERT INTO journal (signalement_id, ancien_statut, nouveau_statut, agent, motif, date) VALUES (1, NULL, 'verifie', 'automatique', 'x', '2999-01-01T00:00:00+00:00')")
    conn.commit(); conn.close()
    assert client.get("/api/notifications", headers=mairie).json()["evenements"] == []


def test_acces_refuse_sans_compte_et_au_citoyen_ou_terrain(client):
    assert client.get("/api/notifications").status_code == 401
    pre = connecter(client, "precol1", "precollecteur")
    assert client.get("/api/notifications", headers=pre).status_code == 403
    assert client.post("/api/notifications/lues").status_code == 401


def test_defi_collectif_compte_les_depotoirs_verifies_sans_donnee_personnelle(client, sig, bons_points):
    assert client.get("/api/public/defi").json() == {"jours": 30, "verifies": 0, "objectif": 50, "atteint": False}
    deposer(client, sig)                                                      # vérifié (avec photo)
    deposer(client, {**bons_points[7], "enqueteur": "E3", "appareil": "A3", "horodatage": sig["horodatage"]}, avec_photo=False)   # à confirmer : ne compte pas
    r = client.get("/api/public/defi")
    assert r.status_code == 200 and r.json()["verifies"] == 1
    assert set(r.json()) == {"jours", "verifies", "objectif", "atteint"}      # ni appareil, ni position, ni identifiant


def test_les_donnees_synthetiques_et_les_essais_ne_comptent_pas_dans_le_defi(client):
    conn = base.ouvrir()
    for synth, essai in ((1, 0), (0, 1)):
        conn.execute("INSERT INTO signalement (lat, lon, recu_le, statut, score, synthetique, essai) VALUES (12.37, -1.52, ?, 'verifie', 90, ?, ?)",
                     (base.maintenant(), synth, essai))
    conn.commit(); conn.close()
    assert client.get("/api/public/defi").json()["verifies"] == 0


def test_historique_de_suivi_du_citoyen_sans_nom_d_agent(client, sig):
    brigade = connecter(client, "brigade1", "brigade")
    r = deposer(client, sig, avec_photo=False)
    sid = 1
    rep = client.post(f"/api/signalements/{sid}/revalider", json={"statut": "verifie", "motif": "Tas constaté sur place"}, headers=brigade)
    assert rep.status_code == 200, rep.text
    s = client.get(f"/api/suivi/{r['code_suivi']}").json()
    assert [h["statut"] for h in s["historique"]] == ["a_confirmer", "verifie"]
    assert "agent de la brigade" in s["historique"][1]["texte"] and "B1" not in str(s) and "brigade1" not in str(s)
    assert "Tas constaté" not in str(s)                                              # le motif interne n'est jamais exposé
