"""Durcissement : entrées absurdes (jamais de 500), limites d'import, lots d'essai, photo plausible, comptes neufs, rafale de zone."""
import base64
import io
import time
from datetime import datetime, timedelta, timezone

import numpy as np
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from PIL import Image

from oregdo.api import signalements
from oregdo.verification import base, controles as c, lot, plausibilite, score as s
from outils_photo import exif_octets, jpeg, photo_neuve


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setenv("OREGDO_DB", str(tmp_path / "d.db"))
    app = FastAPI()
    app.include_router(signalements.router, prefix="/api")
    return TestClient(app, raise_server_exceptions=False)      # un 500 resterait un 500 (et ferait échouer le test)


def corps(sig, **kw):
    return {k: sig[k] for k in ("lat", "lon", "secteur", "enqueteur", "appareil", "horodatage")} | kw


def b64(octets):
    return base64.b64encode(octets).decode()


def bruit_pur(cote=300):
    img = Image.fromarray(np.random.default_rng(5).integers(0, 255, (cote, cote, 3), dtype="uint8"))
    t = io.BytesIO(); img.save(t, "JPEG", quality=90)
    return t.getvalue()


# ------------------------------------------------------------------ 1. entrées absurdes
@pytest.mark.parametrize("piege", [{"lat": "inf"}, {"lat": "nan"}, {"lon": "-inf"}, {"lat": "abc"}, {"lat": None}, {"lon": None},
                                   {"lat": 91}, {"lat": -90.5}, {"lon": 181}, {"lon": 1e308}, {"lat": [1, 2]}, {"lat": {"a": 1}},
                                   {"nature": "x" * 501}, {"enqueteur": "é" * 600}, {"horodatage": "9" * 1000},
                                   {"photos": [b64(jpeg(1))] * 6}, {"photos": ["A" * 5_000_000]}])
def test_entrees_absurdes_donnent_422_en_francais(client, sig, piege):
    r = client.post("/api/signalements", json=corps(sig, **piege))
    assert r.status_code == 422, (piege, r.status_code, r.text[:200])
    assert isinstance(r.json()["detail"], str) and r.json()["detail"]


@pytest.mark.parametrize("extra", [{"nature": {"a": [1, 2]}}, {"nature": 12345}, {"caniveau": ["x"]}, {"caniveau": "peut-être"},
                                   {"horodatage": "pas une date"}, {"taille": 3.14}, {"secteur": "S" * 500}, {"photos": ["pas du base64 !!"]}])
def test_valeurs_bizarres_mais_finies_ne_plantent_pas(client, sig, extra):
    assert client.post("/api/signalements", json=corps(sig, **extra)).status_code == 201


@pytest.mark.parametrize("sid", ["99999999999999999999", "abc", "-1", "0", "1.5", "９"])
def test_identifiant_de_revalidation_invalide(client, sid):
    r = client.post(f"/api/signalements/{sid}/revalider", json={"statut": "verifie", "agent": "A", "motif": "m"})
    assert r.status_code in (404, 422) and r.status_code != 500
    if sid != "0":
        assert r.status_code == 422 or sid == "1.5"


def test_revalidation_champs_geants(client, sig):
    sid = client.post("/api/signalements", json=corps(sig)).json()["id"]
    # L'agent est le compte connecté (le champ « agent » du corps est ignoré) : c'est le motif qui peut être démesuré.
    r = client.post(f"/api/signalements/{sid}/revalider", json={"statut": "verifie", "agent": "A", "motif": "m" * 600})
    assert r.status_code == 422 and "trop long" in r.json()["detail"]


def test_lot_et_import_avec_valeurs_infinies_ne_plantent_pas(client, tmp_path):
    res = lot.verifier_lot([{"lat": "inf", "lon": "nan"}, {"lat": 1e308, "lon": -1e308}, {"lat": 12.3, "lon": "x"}])
    assert [r["statut"] for r in res] == ["rejete"] * 3
    r = client.post("/api/signalements/import", files={"fichier": ("a.csv", b"lat,lon\ninf,1\n1e999,2\n99999,99999\n", "text/csv")})
    assert r.status_code == 200 and r.json()["nb_refusees"] == 2 and r.json()["nb_acceptees"] == 1
    assert c.distance_m(float("inf"), 0, 0, 0) == float("inf") and c.distance_m(99999, 5, -99999, 7) >= 0


# ------------------------------------------------------------------ 2. import
def test_import_trop_gros_ou_trop_long_refuse_proprement(client):
    gros = b"lat,lon\n" + b"12.3,-1.5\n" * 600_000
    r = client.post("/api/signalements/import", files={"fichier": ("g.csv", gros, "text/csv")})
    assert r.status_code == 413 and "volumineux" in r.json()["detail"]
    longues = b"lat,lon\n" + b"1,1\n" * 5001
    r = client.post("/api/signalements/import", files={"fichier": ("l.csv", longues, "text/csv")})
    assert r.status_code == 413 and "Trop de lignes" in r.json()["detail"]


def test_import_1000_lignes_rapide_et_en_une_transaction(tmp_path, bons_points, ref, cfg):
    from oregdo.verification import importation
    lignes = ["lat,lon,enqueteur,appareil,horodatage"]
    base_t = datetime.now(timezone.utc) - timedelta(days=2)
    for i in range(1000):
        p = bons_points[i % len(bons_points)]
        lignes.append(f"{p['lat'] + (i // 60) * 0.0004},{p['lon']},IMP-{i % 50},IMPA-{i},{(base_t + timedelta(minutes=7 * i)).isoformat()}")
    conn = base.ouvrir(tmp_path / "i.db")
    t0 = time.perf_counter()
    r = importation.importer(conn, "m.csv", "\n".join(lignes).encode(), cfg, ref)
    duree = time.perf_counter() - t0
    print(f"\n[perf] import de 1000 lignes : {duree:.2f} s")
    assert r["nb_acceptees"] == 1000 and duree < 15


# ------------------------------------------------------------------ 3. lots d'essai
def test_lot_d_essai_ne_change_ni_stats_ni_liste_ni_depotoirs(client, sig):
    client.post("/api/signalements", json=corps(sig, photos=[b64(photo_neuve())]))
    avant = (client.get("/api/signalements/stats").json(), client.get("/api/signalements").json(), client.get("/api/depotoirs").json())
    res = lot.verifier_pieges(generer=24)
    assert len(res["resultats"]) == 24
    apres = (client.get("/api/signalements/stats").json(), client.get("/api/signalements").json(), client.get("/api/depotoirs").json())
    assert avant[0]["total"] == apres[0]["total"] == 1 and avant[0]["par_statut"] == apres[0]["par_statut"]
    assert apres[0]["nb_essais_masques"] >= 24 and avant[1] == apres[1] and avant[2] == apres[2]
    assert client.get("/api/signalements?avec_essais=1").json()["nombre"] >= 25            # conservés pour l'audit
    assert client.get("/api/signalements/stats?avec_essais=1").json()["total"] >= 25


def test_migration_douce_d_une_ancienne_base(tmp_path):
    import sqlite3
    ancienne = tmp_path / "vieille.db"
    import re
    ancien = base.SCHEMA.read_text(encoding="utf-8")
    ancien = chr(10).join(l for l in ancien.splitlines() if not any(k in l for k in ("essai ", "photo_plausible ", "exif_coherent ")))
    ancien = re.sub(r",\s*\)", ")", ancien)
    c0 = sqlite3.connect(ancienne)
    c0.executescript(ancien)
    c0.execute("INSERT INTO signalement (lat, lon, recu_le, statut, motifs) VALUES (12.3, -1.5, 'x', 'verifie', '[]')")
    c0.commit(); c0.close()
    conn = base.ouvrir(ancienne)
    cols = {r["name"] for r in conn.execute("PRAGMA table_info(signalement)")}
    assert {"essai", "photo_plausible", "exif_coherent"} <= cols
    assert len(base.lister_signalements(conn)) == 1                                       # l'ancienne ligne reste, essai = 0


# ------------------------------------------------------------------ 4. photo plausible, comptes neufs, rafale de zone
def test_photo_plausible_heuristique(cfg):
    ok = lambda o: plausibilite.juger(c.analyser_photo(o), cfg)  # noqa: E731
    assert ok(photo_neuve())[0] is True
    assert "bruit" in ok(bruit_pur())[1] and not ok(bruit_pur())[0]
    uni = io.BytesIO(); Image.new("RGB", (300, 300), (120, 120, 120)).save(uni, "JPEG")
    assert "unie" in ok(uni.getvalue())[1]
    petit = io.BytesIO(); Image.fromarray(np.random.default_rng(1).integers(0, 255, (40, 40, 3), dtype="uint8")).save(petit, "JPEG")
    assert "petite" in ok(petit.getvalue())[1]
    assert not ok(b"pas une image")[0]


def test_image_aleatoire_plus_appareil_neuf_n_est_plus_verifie(tmp_path, sig, ref, cfg):
    conn = base.ouvrir(tmp_path / "t.db")
    r = s.verifier_et_enregistrer(conn, {**sig, "appareil": "NEUF"}, [bruit_pur()], ref, cfg)
    assert r["statut"] == "a_confirmer" and r["score"] <= cfg.verification.sans_photo_plafond
    assert any(m["controle"] == "photo_plausible" and m["etat"] == "echec" for m in r["motifs"])


def test_corroboration_sans_preuve_pas_de_bonus_avec_bruit(tmp_path, sig, ref, cfg):
    conn = base.ouvrir(tmp_path / "t.db")
    s.verifier_et_enregistrer(conn, sig, [bruit_pur()], ref, cfg)
    r = s.verifier_et_enregistrer(conn, {**sig, "enqueteur": "E2", "appareil": "A2"}, [bruit_pur(310)], ref, cfg)
    assert r["statut"] == "a_confirmer"


def test_compte_neuf_plafonne_sauf_exif_coherent_ou_identifiant_connu(tmp_path, sig, ref, cfg):
    conn = base.ouvrir(tmp_path / "t.db")
    neuf = s.verifier_et_enregistrer(conn, sig, [photo_neuve()], ref, cfg)
    assert neuf["score"] <= cfg.verification.nouvel_identifiant_plafond and neuf["statut"] == "verifie"
    assert any(m["controle"] == "regle_nouvel_identifiant" for m in neuf["motifs"])
    # même enquêteur et même appareil, plus tard, ailleurs : plus de plafond
    autre = {**sig, "lat": sig["lat"] + 0.01, "horodatage": (datetime.now(timezone.utc) - timedelta(minutes=5)).isoformat()}
    from outils_photo import jpeg as _j
    connu = s.verifier_et_enregistrer(conn, autre, [photo_neuve()], ref, cfg)
    assert not any(m["controle"] == "regle_nouvel_identifiant" for m in connu["motifs"])
    # compte neuf mais EXIF cohérent : pas de plafond
    d = datetime.now(timezone.utc) - timedelta(hours=1)
    pt = {**sig, "lat": sig["lat"] - 0.02, "enqueteur": "NEUF", "appareil": "NEUFA"}
    avec_exif = s.verifier_et_enregistrer(conn, pt, [jpeg(4242, exif=exif_octets(pt["lat"], pt["lon"], d))], ref, cfg)
    assert avec_exif["score"] > cfg.verification.nouvel_identifiant_plafond


def test_rafale_de_zone_entre_enqueteurs_differents(tmp_path, bons_points, sig, ref, cfg):
    conn = base.ouvrir(tmp_path / "t.db")
    t0 = datetime.now(timezone.utc) - timedelta(hours=2)
    sorties = []
    for i in range(4):
        p = {**bons_points[0], "lat": bons_points[0]["lat"] + i * 0.0003, "enqueteur": f"Z{i}", "appareil": f"ZA{i}",
             "horodatage": (t0 + timedelta(seconds=7 * i)).isoformat()}
        sorties.append(s.verifier_et_enregistrer(conn, p, [photo_neuve()], ref, cfg))
    assert sorties[0]["statut"] == "verifie" and sorties[1]["statut"] == "verifie"
    for r in sorties[2:]:
        assert r["statut"] != "verifie"
        assert any("Rafale coordonnée" in m["motif"] for m in r["motifs"])
