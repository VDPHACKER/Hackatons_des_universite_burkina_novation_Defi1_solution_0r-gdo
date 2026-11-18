"""Routes par acteur (docs/12) : connexion, suivi citoyen, terrain, pré-collecteur, brigade, mairie, administration.
Base temporaire, vrais comptes, vrais jetons signés : l'authentification n'est jamais désactivée ici."""
import base64
from datetime import date, timedelta

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from oregdo import comptes, securite
from oregdo.api import plan, portails, signalements
from oregdo.config import charger_config
from oregdo.planning import depotoirs
from oregdo.verification import base, doublons, score
from outils_photo import photo_neuve

MDP = "mot-de-passe-test"


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setenv("OREGDO_DB", str(tmp_path / "portails.db"))
    monkeypatch.setenv("OREGDO_AUTH", "1")                       # jamais de contournement dans ces tests
    monkeypatch.setattr(depotoirs, "CHEMIN_BASE", tmp_path / "portails.db")
    securite.reinitialiser_limites()
    app = FastAPI()
    for module in (signalements, plan, portails):
        app.include_router(module.router, prefix="/api")
    plan.reinitialiser()
    return TestClient(app)


def compte(ident, role, zone=None, point=None):
    conn = base.ouvrir()
    comptes.creer_utilisateur(conn, ident, ident.upper(), role, MDP, zone, point)
    conn.close()


def entetes(client, ident):
    r = client.post("/api/auth/connexion", json={"identifiant": ident, "mot_de_passe": MDP})
    assert r.status_code == 200, r.text
    return {"Authorization": "Bearer " + r.json()["jeton"]}


def depotoir_verifie(sig, **kw):
    """Signalement avec photo, vérifié puis consolidé en dépotoir. Renvoie l'identifiant du dépotoir."""
    conn, cfg = base.ouvrir(), charger_config()
    score.verifier_et_enregistrer(conn, {**sig, **kw}, [photo_neuve()], cfg=cfg)
    doublons.consolider(conn, cfg)
    did = conn.execute("SELECT id FROM depotoir WHERE statut='verifie'").fetchone()[0]
    conn.close()
    return did


# ------------------------------------------------------------------ anciennes bases
def test_ancienne_base_est_migree_sans_perte(tmp_path):
    """Régression : une base créée avant `code_suivi` doit s'ouvrir (la migration passe avant les index du schéma)."""
    import sqlite3
    chemin = tmp_path / "ancienne.db"
    c = sqlite3.connect(chemin)
    c.execute("CREATE TABLE signalement (id INTEGER PRIMARY KEY AUTOINCREMENT, lat REAL, lon REAL, appareil TEXT, recu_le TEXT NOT NULL, "
              "statut TEXT NOT NULL, motifs TEXT NOT NULL DEFAULT '[]', score REAL, nb_photos INTEGER NOT NULL DEFAULT 0, "
              "source TEXT NOT NULL DEFAULT 'application', synthetique INTEGER NOT NULL DEFAULT 0)")
    c.execute("INSERT INTO signalement (lat, lon, appareil, recu_le, statut, score) VALUES (12.3, -1.5, 'A1', '2026-01-01', 'verifie', 80)")
    c.commit(); c.close()
    conn = base.ouvrir(chemin)
    colonnes = {r["name"] for r in conn.execute("PRAGMA table_info(signalement)")}
    assert {"code_suivi", "utilisateur", "essai"} <= colonnes
    assert conn.execute("SELECT COUNT(*) FROM signalement").fetchone()[0] == 1          # rien n'est perdu
    assert conn.execute("SELECT 1 FROM sqlite_master WHERE name='utilisateur'").fetchone()
    conn.close()


# ------------------------------------------------------------------ connexion
def test_connexion_et_session(client):
    compte("awa", "brigade", zone="Secteur 12")
    assert client.post("/api/auth/connexion", json={"identifiant": "awa", "mot_de_passe": "faux"}).status_code == 401
    assert client.post("/api/auth/connexion", json={"identifiant": "inconnu", "mot_de_passe": MDP}).status_code == 401
    h = entetes(client, "awa")
    moi = client.get("/api/auth/moi", headers=h).json()
    assert moi["identifiant"] == "awa" and moi["role"] == "brigade" and moi["zone"] == "Secteur 12"
    assert client.get("/api/auth/moi").status_code == 401
    assert client.post("/api/auth/deconnexion", headers=h).status_code == 200
    assert client.get("/api/auth/moi", headers=h).status_code == 401              # le jeton est révoqué


def test_verrouillage_apres_echecs_repetes(client):
    compte("awa", "brigade")
    for _ in range(charger_config().securite.verrouillage.echecs_max):
        client.post("/api/auth/connexion", json={"identifiant": "awa", "mot_de_passe": "faux"})
    r = client.post("/api/auth/connexion", json={"identifiant": "awa", "mot_de_passe": MDP})   # même le bon mot de passe
    assert r.status_code == 423 and r.json()["reessayer_dans_s"] > 0 and "Retry-After" in r.headers


def test_compte_desactive_ne_se_connecte_plus(client):
    compte("awa", "brigade")
    compte("chef", "admin")
    assert client.delete("/api/admin/utilisateurs/awa", headers=entetes(client, "chef")).status_code == 200
    assert client.post("/api/auth/connexion", json={"identifiant": "awa", "mot_de_passe": MDP}).status_code == 403


def test_changement_de_mot_de_passe(client):
    compte("awa", "brigade")
    h = entetes(client, "awa")
    assert client.post("/api/auth/mot-de-passe", json={"ancien": "faux", "nouveau": "nouveau-mdp-123"}, headers=h).status_code == 401
    assert client.post("/api/auth/mot-de-passe", json={"ancien": MDP, "nouveau": "court"}, headers=h).status_code == 422
    assert client.post("/api/auth/mot-de-passe", json={"ancien": MDP, "nouveau": "nouveau-mdp-123"}, headers=h).status_code == 200
    assert client.post("/api/auth/connexion", json={"identifiant": "awa", "mot_de_passe": "nouveau-mdp-123"}).status_code == 200


# ------------------------------------------------------------------ citoyen
def test_citoyen_suivi_et_carte_publique(client, sig):
    r = client.post("/api/signalements", json={**sig, "photos": [base64.b64encode(photo_neuve()).decode()]})
    assert r.status_code == 201 and set(r.json()) == {"code_suivi", "statut", "message"}      # réponse réduite, pas de score ni de motifs
    code = r.json()["code_suivi"]
    s = client.get(f"/api/suivi/{code}").json()
    assert s["statut"] == r.json()["statut"] and "lat" not in s and "enqueteur" not in s
    assert client.get("/api/suivi/INCONNU-1234").status_code == 404
    assert client.get("/api/suivi/a b").status_code == 404
    assert s["statut"] == "verifie"
    carte = client.get("/api/public/depotoirs").json()
    assert len(carte["features"]) == 1
    props = carte["features"][0]["properties"]
    assert set(props) == {"niveau_confiance", "synthetique", "ref", "confirmations", "disparu"}
    assert "id" not in props and len(props["ref"]) == 10                                 # référence opaque, jamais l'identifiant interne
    lon, lat = carte["features"][0]["geometry"]["coordinates"]
    assert lon == round(lon, 3) and lat == round(lat, 3)


def test_sante_base_vide(client):
    s = client.get("/api/sante").json()
    assert s["ok"] and s["base_vide"] and not s["demo_chargee"]


# ------------------------------------------------------------------ terrain : collecte d'un agent et import d'un fichier
def test_un_agent_qui_signale_ne_peut_pas_usurper_une_autre_identite(client, sig):
    compte("awa", "brigade")
    r = client.post("/api/signalements", json={**sig, "enqueteur": "usurpe"}, headers=entetes(client, "awa"))
    assert r.status_code == 201 and r.json()["id"]
    conn = base.ouvrir()
    assert conn.execute("SELECT enqueteur FROM signalement").fetchone()[0] == "awa"           # identité forcée au compte
    conn.close()


def test_l_import_d_un_fichier_de_collecte_est_reserve_a_la_brigade_et_a_la_mairie(client, bons_points):
    p = bons_points[0]
    fichier = {"fichier": ("collecte.csv", f"lat,lon\n{p['lat']},{p['lon']}\n".encode(), "text/csv")}
    compte("moussa", "precollecteur"); compte("awa", "brigade"); compte("maire", "mairie")
    assert client.post("/api/signalements/import", files=fichier).status_code == 401
    assert client.post("/api/signalements/import", files=fichier, headers=entetes(client, "moussa")).status_code == 403
    for ident in ("awa", "maire"):
        r = client.post("/api/signalements/import", files=fichier, headers=entetes(client, ident))
        assert r.status_code == 200 and r.json()["nb_acceptees"] == 1, ident


def test_un_ancien_compte_enqueteur_devient_agent_de_la_brigade(client):
    conn = base.ouvrir()
    conn.execute("INSERT INTO utilisateur (identifiant, nom, role, mot_de_passe, actif, cree_le) VALUES ('ancien', 'Ancien', 'enqueteur', 'x', 1, '2026-01-01')")
    conn.commit(); conn.close()
    base._PRETES.clear()                                       # force la migration à la prochaine ouverture
    conn = base.ouvrir()
    assert conn.execute("SELECT role FROM utilisateur WHERE identifiant='ancien'").fetchone()[0] == "brigade"
    conn.close()


# ------------------------------------------------------------------ pré-collecteur
def test_precollecteur_collectes(client):
    compte("moussa", "precollecteur", zone="Secteur 3", point="PR-12")
    h = entetes(client, "moussa")
    assert client.get("/api/precollecteur/profil", headers=h).json()["point"] == "PR-12"
    r = client.post("/api/precollecteur/collectes", json={"kg": 120.5, "nb_menages": 40}, headers=h)
    assert r.status_code == 201 and r.json()["point"] == "PR-12" and r.json()["date"] == date.today().isoformat()
    client.post("/api/precollecteur/collectes", json={"kg": 80, "nb_menages": 25, "date": (date.today() - timedelta(days=2)).isoformat()}, headers=h)
    liste = client.get("/api/precollecteur/collectes", headers=h).json()
    assert liste["totaux"] == {"kg": 200.5, "nb_menages": 65, "nb_collectes": 2}
    assert client.get(f"/api/precollecteur/collectes?du={date.today().isoformat()}", headers=h).json()["totaux"]["nb_collectes"] == 1
    for mauvais in ({"kg": 0}, {"kg": -5}, {"kg": 5001}, {"kg": "abc"}, {"kg": "nan"}, {"kg": 10, "nb_menages": 2001},
                    {"kg": 10, "nb_menages": 1.5}, {"kg": 10, "date": "2999-01-01"}, {"kg": 10, "date": "pas-une-date"}):
        rr = client.post("/api/precollecteur/collectes", json=mauvais, headers=h)
        assert rr.status_code == 422 and isinstance(rr.json()["detail"], str), mauvais


def test_precollecteur_tournee_sans_plan_ou_sans_point(client):
    compte("moussa", "precollecteur", point="PR-12")
    compte("sans", "precollecteur")
    t = client.get("/api/precollecteur/tournee", headers=entetes(client, "moussa")).json()
    assert t["disponible"] is False and t["message"]
    assert client.get("/api/precollecteur/tournee", headers=entetes(client, "sans")).json()["disponible"] is False


# ------------------------------------------------------------------ brigade
def test_file_et_depotoirs_de_la_brigade(client, sig):
    compte("agent", "brigade")
    h = entetes(client, "agent")
    did = depotoir_verifie(sig)
    deps = client.get("/api/brigade/depotoirs", headers=h).json()["depotoirs"]
    assert [d["id"] for d in deps] == [did] and deps[0]["sanction_possible"] is False
    assert client.get("/api/brigade/file", headers=h).json()["nombre"] == 0
    assert client.get("/api/brigade/file?statut=zzz", headers=h).status_code == 400


def test_sanction_exige_sensibilisation_pv_et_bareme(client, sig):
    compte("agent", "brigade")
    h = entetes(client, "agent")
    did = depotoir_verifie(sig)
    bareme = client.get("/api/brigade/bareme", headers=h).json()
    mini, maxi, mult = bareme["amende_min_fcfa"], bareme["amende_max_fcfa"], bareme["recidive_multiplicateur"]
    assert (mini, maxi, mult) == (30000, 50000, 2) and "022-2005" in bareme["base_legale"]

    sanction = {"depotoir_id": did, "type": "sanction", "numero_pv": "PV-001", "montant_fcfa": 40000}
    r = client.post("/api/brigade/interventions", json=sanction, headers=h)
    assert r.status_code == 409 and "sensibilis" in r.json()["detail"]                       # pas de sanction d'emblée
    flagrant = client.post("/api/brigade/interventions", json={**sanction, "flagrant_delit": True}, headers=h)
    assert flagrant.status_code == 409                                                       # flagrant sans motif : refusé

    assert client.post("/api/brigade/interventions", json={"depotoir_id": did, "type": "sensibilisation", "issue": "habitants informés"}, headers=h).status_code == 201
    assert client.get("/api/brigade/depotoirs", headers=h).json()["depotoirs"][0]["sanction_possible"] is True

    assert client.post("/api/brigade/interventions", json={**sanction, "numero_pv": ""}, headers=h).status_code == 422   # PV obligatoire
    assert client.post("/api/brigade/interventions", json={**sanction, "montant_fcfa": mini - 1}, headers=h).status_code == 422
    assert client.post("/api/brigade/interventions", json={**sanction, "montant_fcfa": maxi + 1}, headers=h).status_code == 422
    premiere = client.post("/api/brigade/interventions", json=sanction, headers=h)
    assert premiere.status_code == 201 and premiere.json()["recidive"] is False

    # Récidive : le barème est doublé (l'ancien montant maximal reste valable, le nouveau plafond est maxi × 2).
    rec = client.post("/api/brigade/interventions", json={**sanction, "numero_pv": "PV-003", "montant_fcfa": mini * mult}, headers=h)
    assert rec.status_code == 201 and rec.json()["recidive"] is True
    assert client.post("/api/brigade/interventions", json={**sanction, "numero_pv": "PV-004", "montant_fcfa": maxi * mult + 1}, headers=h).status_code == 422
    assert client.post("/api/brigade/interventions", json={**sanction, "numero_pv": "PV-005", "montant_fcfa": mini}, headers=h).status_code == 422   # sous le barème doublé

    liste = client.get("/api/brigade/interventions", headers=h).json()["interventions"]
    assert len(liste) == 3 and all(i["agent"] == "agent" for i in liste)


def test_flagrant_delit_motive_autorise_la_sanction_directe(client, sig):
    compte("agent", "brigade")
    h = entetes(client, "agent")
    did = depotoir_verifie(sig)
    r = client.post("/api/brigade/interventions", headers=h, json={"depotoir_id": did, "type": "sanction", "numero_pv": "PV-9",
                                                                    "montant_fcfa": 30000, "flagrant_delit": True, "motif_flagrant": "pris sur le fait par la patrouille"})
    assert r.status_code == 201


def test_intervention_sur_depotoir_inconnu_ou_non_verifie(client, sig):
    compte("agent", "brigade")
    h = entetes(client, "agent")
    assert client.post("/api/brigade/interventions", json={"depotoir_id": 999, "type": "sensibilisation"}, headers=h).status_code == 404
    assert client.post("/api/brigade/interventions", json={"depotoir_id": 1, "type": "amende"}, headers=h).status_code == 422
    assert client.post("/api/brigade/interventions", json={"depotoir_id": "x", "type": "sensibilisation"}, headers=h).status_code == 422
    did = depotoir_verifie(sig)
    conn = base.ouvrir()
    conn.execute("UPDATE depotoir SET statut='sans_signalement_valide' WHERE id=?", (did,))
    conn.commit()
    conn.close()
    assert client.post("/api/brigade/interventions", json={"depotoir_id": did, "type": "sensibilisation"}, headers=h).status_code == 409


def test_roles_interdits_sur_la_brigade(client):
    compte("moussa", "precollecteur")
    for ident in ("moussa",):
        h = entetes(client, ident)
        assert client.get("/api/brigade/file", headers=h).status_code == 403
        assert client.post("/api/brigade/interventions", json={"depotoir_id": 1, "type": "sensibilisation"}, headers=h).status_code == 403
        assert client.get("/api/mairie/kpi", headers=h).status_code == 403


# ------------------------------------------------------------------ mairie
def test_kpi_mairie(client, sig):
    compte("maire", "mairie")
    compte("moussa", "precollecteur", point="PR-1")
    compte("agent", "brigade")
    did = depotoir_verifie(sig)
    client.post("/api/precollecteur/collectes", json={"kg": 100, "nb_menages": 30}, headers=entetes(client, "moussa"))
    client.post("/api/brigade/interventions", json={"depotoir_id": did, "type": "sensibilisation", "issue": "informés"}, headers=entetes(client, "agent"))
    k = client.get("/api/mairie/kpi", headers=entetes(client, "maire")).json()
    assert k["depotoirs_verifies"] == 1 and k["signalements"]["total"] == 1
    assert k["interventions"]["sensibilisation"] == 1 and k["interventions"]["sanction"] == 0
    assert k["collectes"] == {"kg": 100.0, "nb_menages": 30, "nb_collectes": 1, "par_point": [{"point": "PR-1", "kg": 100.0, "nb_collectes": 1}]}
    assert client.get("/api/mairie/kpi").status_code == 401


# ------------------------------------------------------------------ administration
def test_admin_comptes_et_garde_fous(client):
    compte("chef", "admin")
    compte("maire", "mairie")
    admin, maire = entetes(client, "chef"), entetes(client, "maire")
    assert client.get("/api/admin/utilisateurs", headers=maire).status_code == 403
    r = client.post("/api/admin/utilisateurs", headers=admin, json={"identifiant": "nouveau", "nom": "Nouvel Agent", "role": "brigade", "mot_de_passe": MDP})
    assert r.status_code == 201 and r.json()["utilisateur"]["role"] == "brigade" and "mot_de_passe" not in r.json()["utilisateur"]
    assert client.post("/api/admin/utilisateurs", headers=admin, json={"identifiant": "nouveau", "nom": "X", "role": "brigade", "mot_de_passe": MDP}).status_code == 409
    assert client.post("/api/admin/utilisateurs", headers=admin, json={"identifiant": "ab", "nom": "X", "role": "brigade", "mot_de_passe": MDP}).status_code == 422
    assert client.post("/api/admin/utilisateurs", headers=admin, json={"identifiant": "autre", "nom": "X", "role": "roi", "mot_de_passe": MDP}).status_code == 422
    assert client.post("/api/admin/utilisateurs", headers=admin, json={"identifiant": "autre", "nom": "X", "role": "brigade", "mot_de_passe": "court"}).status_code == 422
    assert client.delete("/api/admin/utilisateurs/chef", headers=admin).status_code == 409           # pas d'auto-désactivation
    assert client.patch("/api/admin/utilisateurs/chef", headers=admin, json={"role": "mairie"}).status_code == 409
    assert client.patch("/api/admin/utilisateurs/inconnu", headers=admin, json={"nom": "X"}).status_code == 404
    # Changer le rôle révoque les sessions en cours.
    h = entetes(client, "nouveau")
    assert client.patch("/api/admin/utilisateurs/nouveau", headers=admin, json={"role": "mairie"}).status_code == 200
    assert client.get("/api/auth/moi", headers=h).status_code == 401
    audit = client.get("/api/admin/audit?limite=50", headers=admin).json()["evenements"]
    assert {"compte_cree", "compte_modifie"} <= {e["action"] for e in audit}
    assert all("mot_de_passe" not in (e["details"] or "") for e in audit)                              # jamais de secret dans l'audit


def test_admin_etat_et_retrait_demo_sur_base_vide(client):
    compte("chef", "admin")
    h = entetes(client, "chef")
    etat = client.get("/api/admin/etat", headers=h).json()
    assert etat["base_vide"] and etat["nb_utilisateurs"] == 1 and "secret" in etat["secret_source"]
    r = client.post("/api/admin/demo/retirer", headers=h)
    assert r.status_code == 200 and r.json()["retires"]["signalements"] == 0


def test_retrait_demo_ne_touche_pas_aux_vrais_signalements(client, sig):
    compte("chef", "admin")
    h = entetes(client, "chef")
    depotoir_verifie(sig)                                                                            # vrai (non synthétique)
    client.post("/api/admin/demo/retirer", headers=h)
    conn = base.ouvrir()
    assert conn.execute("SELECT COUNT(*) FROM signalement").fetchone()[0] == 1
    assert conn.execute("SELECT COUNT(*) FROM depotoir WHERE statut='verifie'").fetchone()[0] == 1
    conn.close()


# ------------------------------------------------------------------ avis de voisins (« moi aussi je le vois » / « n'est plus là »)
def _depot_et_ref(client, sig):
    depotoir_verifie(sig)
    conn = base.ouvrir()
    d = conn.execute("SELECT id, lat, lon FROM depotoir").fetchone()
    conn.close()
    ref = client.get("/api/public/depotoirs").json()["features"][0]["properties"]["ref"]
    return d, ref


def _avis(client, ref, typ, appareil, d, decalage=0.0003):
    return client.post(f"/api/public/depotoirs/{ref}/avis", json={"type": typ, "appareil": appareil, "lat": d["lat"] + decalage, "lon": d["lon"]})


def test_avis_present_entre_dans_le_pipeline_comme_signalement_d_un_autre_appareil(client, sig):
    d, ref = _depot_et_ref(client, sig)
    r = _avis(client, ref, "present", "VOISIN-1", d)                                # ~33 m du tas
    assert r.status_code == 201 and "confirmation" in r.json()["message"]
    conn = base.ouvrir()
    ligne = conn.execute("SELECT source, appareil, lat, lon, depotoir_id FROM signalement WHERE source='soutien'").fetchone()
    assert ligne["appareil"] == "VOISIN-1" and abs(ligne["lat"] - d["lat"]) < 1e-9 and abs(ligne["lon"] - d["lon"]) < 1e-9   # à la position du tas
    avis = conn.execute("SELECT type, distance_m FROM avis").fetchone()
    assert avis["type"] == "present" and 20 < avis["distance_m"] < 50               # la distance mesurée est conservée comme preuve
    conn.close()
    # Deuxième voisin : l'avis compte une fois par appareil, le dépotoir reste UN seul dépotoir.
    assert _avis(client, ref, "present", "VOISIN-2", d).status_code == 201
    conn = base.ouvrir()
    assert conn.execute("SELECT COUNT(*) FROM depotoir WHERE statut='verifie'").fetchone()[0] == 1
    assert conn.execute("SELECT COUNT(DISTINCT appareil) FROM avis WHERE type='present'").fetchone()[0] == 2
    conn.close()


def test_avis_trop_loin_refuse_avec_explication(client, sig):
    d, ref = _depot_et_ref(client, sig)
    r = _avis(client, ref, "present", "LOIN-1", d, decalage=0.005)                  # ~550 m
    assert r.status_code == 422 and "approchez-vous" in r.json()["detail"]
    conn = base.ouvrir()
    assert conn.execute("SELECT COUNT(*) FROM avis").fetchone()[0] == 0              # rien d'enregistré
    conn.close()


def test_un_seul_avis_par_appareil_et_par_type(client, sig):
    d, ref = _depot_et_ref(client, sig)
    assert _avis(client, ref, "present", "VOISIN-1", d).status_code == 201
    r = _avis(client, ref, "present", "VOISIN-1", d)
    assert r.status_code == 409 and "déjà" in r.json()["detail"]
    assert _avis(client, ref, "disparu", "VOISIN-1", d).status_code == 201           # un autre TYPE d'avis reste possible


def test_avis_disparu_ne_supprime_rien_et_signale_a_la_brigade(client, sig):
    compte("agent", "brigade")
    d, ref = _depot_et_ref(client, sig)
    r1 = _avis(client, ref, "disparu", "V1", d)
    assert r1.status_code == 201 and r1.json()["a_reverifier"] is False              # un seul appareil : pas assez
    r2 = _avis(client, ref, "disparu", "V2", d)
    assert r2.json()["a_reverifier"] is True and "revérifier" in r2.json()["message"]
    conn = base.ouvrir()
    assert conn.execute("SELECT statut FROM depotoir WHERE id=?", (d["id"],)).fetchone()[0] == "verifie"     # JAMAIS supprimé
    conn.close()
    deps = client.get("/api/brigade/depotoirs", headers=entetes(client, "agent")).json()["depotoirs"]
    assert deps[0]["a_reverifier"] is True and deps[0]["avis_disparu"] == 2
    carte = client.get("/api/public/depotoirs").json()["features"][0]["properties"]
    assert carte["disparu"] == 2


def test_avis_entrees_invalides(client, sig):
    d, ref = _depot_et_ref(client, sig)
    url = f"/api/public/depotoirs/{ref}/avis"
    assert client.post(url, json={"type": "zzz", "appareil": "A", "lat": d["lat"], "lon": d["lon"]}).status_code == 422
    assert client.post(url, json={"type": "present", "appareil": "", "lat": d["lat"], "lon": d["lon"]}).status_code == 422
    assert client.post(url, json={"type": "present", "appareil": "A"}).status_code == 422                  # GPS absent
    assert client.post(url, json={"type": "present", "appareil": "A", "lat": "nan", "lon": d["lon"]}).status_code == 422
    assert client.post(url, json={"type": "present", "appareil": "A", "lat": 999, "lon": d["lon"]}).status_code == 422
    assert client.post("/api/public/depotoirs/inconnu123/avis", json={"type": "present", "appareil": "A", "lat": d["lat"], "lon": d["lon"]}).status_code == 404


def test_la_reference_publique_est_stable_et_ne_se_devine_pas(client, sig):
    d, ref = _depot_et_ref(client, sig)
    assert client.get("/api/public/depotoirs").json()["features"][0]["properties"]["ref"] == ref          # stable d'un appel à l'autre
    assert ref != str(d["id"]) and securite.ref_depotoir(d["id"]) == ref
    assert securite.ref_depotoir(d["id"] + 1) != ref


def test_un_signalement_renvoye_apres_coupure_n_est_enregistre_qu_une_fois(client, sig):
    """Le téléphone renvoie le même signalement (même clé) quand la réponse s'est perdue : même code de suivi, aucun doublon."""
    corps = {**sig, "cle_client": "f0b1c2d3-0000-4000-8000-123456789abc"}
    r1 = client.post("/api/signalements", json=corps)
    r2 = client.post("/api/signalements", json=corps)
    assert r1.status_code == r2.status_code == 201
    assert r1.json()["code_suivi"] == r2.json()["code_suivi"]
    from oregdo.verification import base
    conn = base.ouvrir()
    assert conn.execute("SELECT COUNT(*) FROM signalement").fetchone()[0] == 1
    conn.close()


# ------------------------------------------------------------------ communication entre les profils, d'un bout à l'autre
def test_un_signalement_circule_du_citoyen_a_la_brigade_puis_a_la_mairie(client, sig):
    """Le parcours que le jury suivra : citoyen → brigade → citoyen (suivi) → carte publique → brigade (intervention)
    → mairie (tableau de bord) ; voisins → brigade (à revérifier) ; pré-collecteur → mairie (collectes)."""
    compte("agent", "brigade"); compte("maire", "mairie"); compte("moussa", "precollecteur", point="PR-1")
    brigade, mairie, precol = entetes(client, "agent"), entetes(client, "maire"), entetes(client, "moussa")
    # 1. Le citoyen signale sans compte et sans photo : « à confirmer », avec un code de suivi.
    r = client.post("/api/signalements", json={**sig, "appareil": "TEL-CITOYEN"})
    assert r.status_code == 201 and r.json()["statut"] == "a_confirmer"
    code = r.json()["code_suivi"]
    assert client.get(f"/api/suivi/{code}").json()["statut"] == "a_confirmer"
    assert client.get("/api/public/depotoirs").json()["features"] == []            # pas encore sur la carte publique
    # 2. La brigade le trouve dans sa file et le confirme sur place.
    file = client.get("/api/brigade/file", headers=brigade).json()
    assert file["nombre"] == 1
    sid = file["signalements"][0]["id"]
    assert client.post(f"/api/signalements/{sid}/revalider", json={"statut": "verifie", "motif": "Vérifié sur place"}, headers=brigade).status_code == 200
    assert client.get("/api/brigade/file", headers=brigade).json()["nombre"] == 0
    # 3. Le citoyen voit le changement avec son code, et le tas apparaît sur la carte publique.
    suivi = client.get(f"/api/suivi/{code}").json()
    assert suivi["statut"] == "verifie" and suivi["historique"][-1]["statut"] == "verifie"
    carte = client.get("/api/public/depotoirs").json()["features"]
    assert len(carte) == 1
    # 4. La brigade sensibilise ; la mairie le voit dans son tableau de bord.
    did = client.get("/api/brigade/depotoirs", headers=brigade).json()["depotoirs"][0]["id"]
    assert client.post("/api/brigade/interventions", json={"depotoir_id": did, "type": "sensibilisation", "issue": "habitants informés"}, headers=brigade).status_code == 201
    k = client.get("/api/mairie/kpi", headers=mairie).json()
    assert k["depotoirs_verifies"] == 1 and k["interventions"]["sensibilisation"] == 1
    # 5. Deux voisins disent que le tas n'est plus là : la brigade doit revérifier (rien n'est supprimé).
    ref, (lon, lat) = carte[0]["properties"]["ref"], carte[0]["geometry"]["coordinates"]
    conn = base.ouvrir(); d = conn.execute("SELECT lat, lon FROM depotoir").fetchone(); conn.close()
    for v in ("VOISIN-1", "VOISIN-2"):
        assert client.post(f"/api/public/depotoirs/{ref}/avis", json={"type": "disparu", "appareil": v, "lat": d["lat"], "lon": d["lon"]}).status_code == 201
    assert client.get("/api/brigade/depotoirs", headers=brigade).json()["depotoirs"][0]["a_reverifier"] is True
    # 6. Le pré-collecteur saisit une collecte ; la mairie la retrouve.
    assert client.post("/api/precollecteur/collectes", json={"kg": 75, "nb_menages": 20}, headers=precol).status_code == 201
    assert client.get("/api/mairie/kpi", headers=mairie).json()["collectes"]["nb_collectes"] == 1
    # 7. Chacun reste dans son rôle : le citoyen ne lit pas la file, le pré-collecteur ne revalide pas.
    assert client.get("/api/brigade/file").status_code == 401
    assert client.post(f"/api/signalements/{sid}/revalider", json={"statut": "rejete", "motif": "essai"}, headers=precol).status_code == 403
