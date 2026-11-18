"""Tests du score, des statuts et de la chaîne complète."""
from datetime import datetime, timedelta, timezone

import pytest

from oregdo.verification import base, controles as c, score as s
from outils_photo import jpeg, exif_octets, photo_neuve


@pytest.fixture
def conn(tmp_path):
    return base.ouvrir(tmp_path / "t.db")


def poster(conn, sig, ref, cfg, photos=None):
    """Par défaut chaque signalement porte une photo neuve (sans photo il serait plafonné à « à confirmer »)."""
    return s.verifier_et_enregistrer(conn, sig, [photo_neuve()] if photos is None else photos, ref, cfg)


def test_bon_signalement_avec_photo_est_verifie(conn, sig, ref, cfg):
    r = poster(conn, sig, ref, cfg)
    assert r["statut"] == "verifie" and r["score"] >= cfg.verification.seuils.verifie
    assert {"position", "lieu_possible", "doublons", "photo_reutilisee", "exif", "horodatage", "corroboration", "photo_plausible"} <= {m["controle"] for m in r["motifs"]}


def test_sans_photo_et_sans_corroboration_plafonne_a_confirmer(conn, sig, ref, cfg):
    r = poster(conn, sig, ref, cfg, photos=[])
    assert r["statut"] == "a_confirmer" and r["score"] <= cfg.verification.sans_photo_plafond
    assert any(m["controle"] == "regle_sans_photo" for m in r["motifs"])


def test_dix_points_plausibles_sans_photo_noms_distincts_aucun_verifie(conn, bons_points, ref, cfg):
    for i, p in enumerate(bons_points[:10]):
        r = poster(conn, {**p, "enqueteur": f"X{i}", "appareil": f"XA{i}"}, ref, cfg, photos=[])
        assert r["statut"] == "a_confirmer"


def test_deux_faux_enqueteurs_sans_photo_restent_a_confirmer(conn, sig, ref, cfg):
    premier = poster(conn, sig, ref, cfg, photos=[])
    second = poster(conn, {**sig, "enqueteur": "E2", "appareil": "A2"}, ref, cfg, photos=[])
    assert premier["statut"] == "a_confirmer" and second["statut"] == "a_confirmer"
    assert any("aucune photo plausible" in m["message"] if "message" in m else "aucune photo plausible" in m["motif"] for m in second["motifs"])


def test_corroboration_avec_une_photo_plausible_leve_le_plafond(conn, sig, ref, cfg):
    premier = poster(conn, sig, ref, cfg, photos=[])
    assert premier["statut"] == "a_confirmer"
    second = poster(conn, {**sig, "enqueteur": "E2", "appareil": "A2"}, ref, cfg)        # photo plausible
    assert second["statut"] == "verifie"
    assert base.lire_signalement(conn, premier["id"])["statut"] == "verifie"      # le premier est promu
    assert base.journal_du_signalement(conn, premier["id"])[-1]["agent"] == "automatique"


@pytest.mark.parametrize("e,a", [("E1", "A2"), ("E2", "A1")])
def test_corroboration_meme_enqueteur_ou_meme_appareil_ne_compte_pas(conn, sig, ref, cfg, e, a):
    poster(conn, sig, ref, cfg)
    r = poster(conn, {**sig, "enqueteur": e, "appareil": a}, ref, cfg)
    assert not any(m["controle"] == "corroboration" and m["etat"] == "ok" for m in r["motifs"])


def test_non_applicable_penalise_peu(cfg):
    ok = [c.Resultat(n, c.OK, 1, "") for n in vars(cfg.verification.poids)]
    na = [c.Resultat("exif", c.NON_APPLICABLE, 0, "")] + [r for r in ok if r.controle != "exif"]
    assert s.calculer_score(ok, cfg)[0] - s.calculer_score(na, cfg)[0] == cfg.verification.non_applicable_penalite


def test_bonus_de_corroboration_plafonne_a_100(cfg):
    res = [c.Resultat(n, c.OK, 1, "", None, n == "corroboration") for n in vars(cfg.verification.poids)]
    assert s.calculer_score(res, cfg)[0] == 100


def test_hors_zone_dans_eau_zero_zero_sont_rejetes_et_conserves(conn, sig, ref, cfg):
    p = ref.eau.context.representative_point()
    pieges = [{**sig, "lat": 14, "lon": 2, "appareil": "B1"}, {**sig, "lat": 0, "lon": 0, "appareil": "B2"},
              {**sig, "lat": p.y, "lon": p.x, "appareil": "B3"}, {**sig, "lat": sig["lon"], "lon": sig["lat"], "appareil": "B4"}]
    for x in pieges:
        assert poster(conn, x, ref, cfg)["statut"] == "rejete"
    assert len(base.lister_signalements(conn, "rejete")) == 4
    assert all(m["motif"] for m in base.lister_signalements(conn)[0]["motifs"])


def test_futur_rejete(conn, sig, ref, cfg):
    futur = (datetime.now(timezone.utc) + timedelta(days=1)).isoformat()
    assert poster(conn, {**sig, "horodatage": futur}, ref, cfg)["statut"] == "rejete"


def test_photo_reutilisee_ne_peut_pas_etre_verifiee(conn, sig, ref, cfg, bons_points):
    img = jpeg(20)
    assert poster(conn, sig, ref, cfg, [img])["statut"] == "verifie"
    autre = {**bons_points[5], "enqueteur": "E2", "appareil": "A2", "horodatage": sig["horodatage"]}
    r = poster(conn, autre, ref, cfg, [jpeg(20, taille=128, qualite=45)])
    assert r["statut"] != "verifie"
    assert any(m["controle"] == "photo_reutilisee" and m["etat"] == "echec" for m in r["motifs"])


def test_gonflage_meme_appareil_rejete_puis_autre_enqueteur_corrobore(conn, sig, ref, cfg):
    assert poster(conn, sig, ref, cfg)["statut"] == "verifie"
    assert poster(conn, sig, ref, cfg)["statut"] == "rejete"
    autre = {**sig, "enqueteur": "E2", "appareil": "A2"}
    r = poster(conn, autre, ref, cfg)
    assert r["statut"] == "verifie"
    assert any(m["controle"] == "corroboration" and m["etat"] == "ok" for m in r["motifs"])


def test_photo_corrompue_ne_plante_pas(conn, sig, ref, cfg):
    r = poster(conn, sig, ref, cfg, [b"\x00\x01 corrompu"])
    assert r["statut"] in ("verifie", "a_confirmer", "rejete")
