"""Pièges en direct (jury) dans le vrai pipeline, sécurité par jetons, export OSM et marquage synthétique."""
import base64

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from oregdo.api import plan, signalements
from oregdo.planning import depotoirs
from oregdo.verification import base, lot
from outils_photo import photo_neuve

JURY, AGENT = {"X-Oregdo-Token": "jury-demo"}, {"X-Oregdo-Token": "agent-demo"}


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setenv("OREGDO_DB", str(tmp_path / "p.db"))
    monkeypatch.setattr(depotoirs, "CHEMIN_BASE", tmp_path / "p.db")     # le plan lit la même base temporaire
    app = FastAPI()
    app.include_router(signalements.router, prefix="/api")
    app.include_router(plan.router, prefix="/api")
    plan.reinitialiser()
    return TestClient(app)


def vrai_depotoir(sig, synthetique=False, **kw):
    """Signalement réel (hors lot d'essai) vérifié puis consolidé en dépotoir."""
    from oregdo.config import charger_config
    from oregdo.verification import doublons, score
    conn, cfg = base.ouvrir(), charger_config()
    r = score.verifier_et_enregistrer(conn, {**sig, **kw}, [photo_neuve()], cfg=cfg, synthetique=synthetique)
    doublons.consolider(conn, cfg)
    conn.close()
    return r


def bon(sig, **kw):
    return {**sig, "photos": [base64.b64encode(photo_neuve()).decode()], **kw}


# ------------------------------------------------------------------ verifier_lot
def test_verifier_lot_format_exact_et_conservation(client, sig, bons_points):
    res = lot.verifier_lot([bon(sig), {"lat": 0, "lon": 0, "piege": True}, {"lat": 14, "lon": 2}])
    assert [set(r) for r in res] == [{"id", "statut", "score", "motifs", "piege"}] * 3
    assert res[0]["statut"] == "verifie" and res[1]["statut"] == "rejete"
    assert [r["piege"] for r in res] == [False, True, True]          # défaut : piège = rejeté
    m = res[1]["motifs"][0]
    assert {"ok", "message", "points"} <= set(m) and m["ok"] is False and "(0, 0)" in m["message"]
    conn = base.ouvrir()
    assert conn.execute("SELECT COUNT(*) FROM signalement WHERE source='jury'").fetchone()[0] == 3
    conn.close()


def test_generer_pieges_varies_reproductibles_et_aucun_verifie():
    a, b = lot.generer_pieges(24, graine=3), lot.generer_pieges(24, graine=3)
    assert [x["cas"] for x in a] == [x["cas"] for x in b] and len(a) == 24
    cas = {x["cas"].replace("_origine", "") for x in lot.generer_pieges(40, graine=3)}
    assert set(lot.CAS_PIEGES) <= cas


def test_route_pieges_generer_et_resume(client):
    r = client.post("/api/alea/pieges", json={"generer": 32}, headers=JURY)
    assert r.status_code == 200
    d = r.json()
    assert len(d["resultats"]) == 32
    res = d["resume"]
    assert res["verifies"] + res["a_confirmer"] + res["rejetes"] == 32 and res["pieges_verifies"] == 0
    assert res["rejetes"] >= 24


def test_route_pieges_signalements_fournis_et_erreurs(client, sig):
    r = client.post("/api/alea/pieges", json={"signalements": [{"lat": 12.3, "lon": "abc"}, {"lat": 0, "lon": 0}]}, headers=JURY)
    assert r.status_code == 200 and r.json()["resume"]["rejetes"] == 2
    assert client.post("/api/alea/pieges", json={}, headers=JURY).status_code == 422
    assert client.post("/api/alea/pieges", json={"generer": 100000}, headers=JURY).status_code == 422


def test_alea_signalements_pieges_ne_change_pas_le_plan(client, sig, bons_points):
    for i in range(3):          # quelques vrais dépotoirs vérifiés pour que le plan ne soit pas vide
        vrai_depotoir(bons_points[i], enqueteur=f"R{i}", appareil=f"RA{i}", horodatage=sig["horodatage"])
    avant = client.post("/api/plan/recalculer", headers=JURY).json()
    assert avant["kpi"]["nb_depotoirs_verifies"] >= 3
    r = client.post("/api/alea", json={"type": "signalements_pieges", "params": {"generer": 24, "graine": 2026}}, headers=JURY).json()
    assert len(r["resultats"]) == 24
    assert r["resume"]["pieges_verifies"] == 0, [x for x in r["resultats"] if x["statut"] == "verifie"]   # le piège fautif, pour comprendre
    assert r["plan_modifie"] is False and r["plan"]["empreinte"] == avant["empreinte"]
    assert "rejeté" in r["message"]


# ------------------------------------------------------------------ sécurité
@pytest.fixture
def auth(monkeypatch):
    monkeypatch.setenv("OREGDO_AUTH", "1")


def _entetes(role):
    """Crée un vrai compte dans la base temporaire et renvoie son en-tête `Authorization: Bearer`."""
    from oregdo import comptes, securite
    conn = base.ouvrir()
    ident = f"{role}-test"
    comptes.creer_utilisateur(conn, ident, ident, role, "mot-de-passe-test")
    jeton, _ = securite.creer_jeton(conn, ident, role)
    conn.close()
    return {"Authorization": f"Bearer {jeton}"}


def test_revalidation_protegee(client, auth, sig):
    client.post("/api/signalements", json={**sig})                                     # création ouverte (citoyen)
    conn = base.ouvrir()
    sid = conn.execute("SELECT id FROM signalement").fetchone()[0]
    conn.close()
    url, corps = f"/api/signalements/{sid}/revalider", {"statut": "rejete", "motif": "test"}
    assert client.post(url, json=corps).status_code == 401                              # sans jeton
    assert client.post(url, json=corps, headers={"Authorization": "Bearer faux.jeton"}).status_code == 401
    assert client.post(url, json=corps, headers=_entetes("precollecteur")).status_code == 403   # mauvais rôle
    assert client.post(url, json=corps, headers=_entetes("brigade")).status_code == 200
    assert client.post(url, json=corps, headers=_entetes("admin")).status_code == 200       # l'admin peut tout
    assert client.get("/api/signalements").status_code == 401                           # la liste complète est réservée
    assert client.get("/api/signalements", headers=_entetes("mairie")).status_code == 200


def test_routes_de_pilotage_protegees(client, auth):
    """Scénario, plan, simulation et aléas de l'épreuve en direct : mairie (l'admin passe toujours). La brigade n'y a pas accès."""
    mairie_ou_admin = [("put", "/api/scenario", {}), ("post", "/api/plan/recalculer", None), ("post", "/api/simulation/run", {"jours": 1}),
                       ("post", "/api/alea", {"type": "saison_pluies"}), ("post", "/api/alea/pieges", {"generer": 1})]
    brigade, mairie, enqueteur = _entetes("brigade"), _entetes("mairie"), _entetes("precollecteur")
    for methode, url, corps in mairie_ou_admin:
        envoyer = getattr(client, methode)
        kw = {"json": corps} if corps is not None else {}
        assert envoyer(url, **kw).status_code == 401, url
        assert envoyer(url, headers=brigade, **kw).status_code == 403, url
        assert envoyer(url, headers=enqueteur, **kw).status_code == 403, url
    assert client.put("/api/scenario", json={}, headers=mairie).status_code == 200
    assert client.post("/api/alea/pieges", json={"generer": 1}, headers=mairie).status_code == 200      # épreuve en direct par la mairie
    assert client.post("/api/alea", json={"type": "saison_pluies"}, headers=mairie).status_code == 200
    assert client.get("/api/scenario").status_code == 200                               # lecture ouverte (carte publique)


def test_auth_desactivable(client, monkeypatch):
    monkeypatch.setenv("OREGDO_AUTH", "0")
    assert client.put("/api/scenario", json={}).status_code == 200


# ------------------------------------------------------------------ synthétique et export OSM
def test_export_osm_refuse_les_synthetiques_sauf_demo(client, sig):
    assert vrai_depotoir(sig, synthetique=True)["statut"] == "verifie"
    assert client.get("/api/depotoirs").json()["synthetique"] is True
    assert client.get("/api/signalements/stats").json()["synthetique"] is True
    r = client.get("/api/export/osm")
    assert r.status_code == 409 and "synthétiques" in r.json()["detail"]
    d = client.get("/api/export/osm?demo=1").json()
    assert d["nombre"] == 1 and "DÉMONSTRATION" in d["osm"]
    tags = d["geojson"]["features"][0]["properties"]
    assert not any(k.startswith(("laabal", "oregdo")) for k in tags) and {"note", "source", "check_date", "landuse"} <= set(tags)
    assert "DÉMONSTRATION" in tags["note"]


def test_export_osm_reel_sans_demo(client, sig):
    conn = base.ouvrir()
    from oregdo.config import charger_config
    from oregdo.verification import doublons, score
    score.verifier_et_enregistrer(conn, {**sig, "source": "application"}, [photo_neuve()], cfg=charger_config())
    doublons.consolider(conn, charger_config())
    conn.close()
    r = client.get("/api/export/osm")
    assert r.status_code == 200 and r.json()["nombre"] == 1 and "DÉMONSTRATION" not in r.json()["osm"]
    assert client.get("/api/depotoirs").json()["synthetique"] is False


@pytest.mark.parametrize("graines", [range(0, 30), range(1000, 1030)])
def test_aucun_piege_ne_passe_verifie_quel_que_soit_le_tirage(client, sig, bons_points, graines):
    """Les pièges sont tirés au hasard pendant l'épreuve : on balaie 60 tirages, avec de vrais dépotoirs déjà en base."""
    from oregdo.verification import lot
    for i in range(3):
        vrai_depotoir(bons_points[i], enqueteur=f"R{i}", appareil=f"RA{i}", horodatage=sig["horodatage"])
    fautifs = []
    for g in graines:
        res = lot.verifier_pieges(generer=24, graine=g)
        fautifs += [(g, r.get("cas"), r.get("score")) for r in res["resultats"] if r["statut"] == "verifie"]
    assert not fautifs, fautifs
