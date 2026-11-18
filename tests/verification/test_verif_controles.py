"""Tests des contrôles, avec des signalements piégés."""
import pytest
from datetime import datetime, timedelta, timezone

from outils_photo import jpeg, exif_octets
from oregdo.verification import controles as c



def test_position_correcte(sig, ref, cfg):
    r = c.controle_position(sig, ref, cfg)
    assert r.etat == c.OK and r.fraction == 1


def test_position_hors_commune(sig, ref, cfg):
    r = c.controle_position({**sig, "lat": 14.0, "lon": 2.0}, ref, cfg)
    assert r.etat == c.ECHEC and r.gravite == c.BLOQUANT and "dehors" in r.motif


def test_position_zero_zero(sig, ref, cfg):
    r = c.controle_position({**sig, "lat": 0, "lon": 0}, ref, cfg)
    assert r.gravite == c.BLOQUANT and "(0, 0)" in r.motif


def test_position_inversee(sig, ref, cfg):
    r = c.controle_position({**sig, "lat": sig["lon"], "lon": sig["lat"]}, ref, cfg)
    assert r.gravite == c.BLOQUANT and "inversées" in r.motif


def test_position_illisible(sig, ref, cfg):
    assert c.controle_position({**sig, "lat": "abc"}, ref, cfg).gravite == c.BLOQUANT
    assert c.controle_position({**sig, "lat": None}, ref, cfg).gravite == c.BLOQUANT


def test_secteur_different_ou_absent(sig, ref, cfg):
    autre = next(n for _, n, _ in ref.secteurs if n != sig["secteur"])
    r = c.controle_position({**sig, "secteur": autre}, ref, cfg)
    assert r.etat == c.PARTIEL and "ne correspond pas" in r.motif
    assert c.controle_position({**sig, "secteur": None}, ref, cfg).etat == c.PARTIEL


def test_lieu_dans_leau(sig, ref, cfg):
    p = ref.eau.context.representative_point() if hasattr(ref.eau, "context") else None
    assert p is not None
    r = c.controle_lieu({**sig, "lat": p.y, "lon": p.x}, ref, cfg)
    assert r.etat == c.ECHEC and "plan d'eau" in r.motif


def test_lieu_sur_laeroport(sig, ref, cfg):
    p = ref.aeroport.context.representative_point()
    r = c.controle_lieu({**sig, "lat": p.y, "lon": p.x}, ref, cfg)
    assert r.gravite == c.BLOQUANT and "aéroport" in r.motif


def test_lieu_possible(sig, ref, cfg):
    assert c.controle_lieu(sig, ref, cfg).etat == c.OK


def hist_de(sig, **kw):
    return {"id": 1, "lat": sig["lat"], "lon": sig["lon"], "enqueteur": "E9", "appareil": "A9",
            "horodatage": sig["horodatage"], "statut": "verifie", **kw}


def test_doublon_autre_enqueteur_est_une_confirmation(sig, cfg):
    h = [hist_de(sig, horodatage=(datetime.now(timezone.utc) - timedelta(days=2)).isoformat())]
    assert c.controle_doublons(sig, h, cfg).etat == c.OK
    assert c.controle_corroboration(sig, h, cfg).etat == c.NEUTRE            # aucune preuve photo/EXIF : pas de bonus
    h[0]["photo_plausible"] = 1
    assert c.controle_corroboration(sig, h, cfg).etat == c.OK
    assert c.controle_corroboration(sig, [{**h[0], "photo_plausible": 0}], cfg, preuve_moi=True).etat == c.OK


def test_gonflage_meme_appareil_en_quelques_secondes(sig, cfg):
    h = [hist_de(sig, enqueteur="E1", appareil="A1")]
    r = c.controle_doublons(sig, h, cfg)
    assert r.gravite == c.BLOQUANT and "gonflage" in r.motif
    assert c.controle_corroboration(sig, h, cfg).etat == c.NEUTRE


def test_meme_enqueteur_plus_tard_pas_une_confirmation(sig, cfg):
    h = [hist_de(sig, enqueteur="E1", appareil="A1", horodatage=(datetime.now(timezone.utc) - timedelta(days=3)).isoformat())]
    r = c.controle_doublons(sig, h, cfg)
    assert r.gravite == c.GRAVE
    assert c.controle_corroboration(sig, h, cfg).etat == c.NEUTRE


def test_photo_reutilisee_et_copie_recompressee(cfg):
    original = c.analyser_photo(jpeg(1))
    connues = [(5, original["empreinte"])]
    copie = c.analyser_photo(jpeg(1, taille=128, qualite=40))
    assert c.controle_photo([copie], connues, cfg).gravite == c.GRAVE
    autre = c.analyser_photo(jpeg(2))
    assert c.controle_photo([autre], connues, cfg).etat == c.OK


def test_photo_absente_ou_illisible(cfg):
    assert c.controle_photo([], [], cfg).etat == c.NON_APPLICABLE
    assert c.analyser_photo(b"pas une image") == {"erreur": "photo illisible ou format inconnu"}
    assert c.controle_photo([c.analyser_photo(b"x")], [], cfg).etat == c.ECHEC


def test_exif_coherent_incoherent_absent(sig, cfg):
    d = datetime.now(timezone.utc) - timedelta(hours=1)
    bon = c.analyser_photo(jpeg(3, exif=exif_octets(sig["lat"], sig["lon"], d)))
    assert c.controle_exif([bon], sig, cfg).etat == c.OK
    loin = c.analyser_photo(jpeg(4, exif=exif_octets(sig["lat"] + 0.05, sig["lon"], d)))
    assert c.controle_exif([loin], sig, cfg).gravite == c.GRAVE
    vieux = c.analyser_photo(jpeg(5, exif=exif_octets(sig["lat"], sig["lon"], d - timedelta(days=30))))
    assert c.controle_exif([vieux], sig, cfg).etat == c.PARTIEL
    sans = c.analyser_photo(jpeg(6))
    r = c.controle_exif([sans], sig, cfg)
    assert r.etat == c.NON_APPLICABLE and "indice faible" in r.motif


def test_horodatage_futur(sig, cfg):
    futur = (datetime.now(timezone.utc) + timedelta(days=2)).isoformat()
    assert c.controle_horodatage({**sig, "horodatage": futur}, [], cfg).gravite == c.BLOQUANT
    assert c.controle_horodatage({**sig, "horodatage": "n'importe quoi"}, [], cfg).etat == c.ECHEC
    assert c.controle_horodatage({**sig, "horodatage": None}, [], cfg).etat == c.NON_APPLICABLE
    assert c.controle_horodatage(sig, [], cfg).etat == c.OK


def test_rafale_impossible_meme_appareil(sig, cfg):
    loin = hist_de(sig, lat=sig["lat"] + 0.1, appareil="A1", enqueteur="E1")
    r = c.controle_horodatage(sig, [loin], cfg)
    assert r.gravite == c.BLOQUANT and "impossible" in r.motif


def test_rafale_trop_de_signalements(sig, cfg):
    n = cfg.verification.rafale.max_signalements_identiques
    h = [hist_de(sig, id=i, appareil="A1", enqueteur="E1", lat=sig["lat"] + 0.0001 * i) for i in range(n)]
    assert "Rafale" in c.controle_horodatage(sig, h, cfg).motif


def test_classifieur_coupe_par_defaut(cfg):
    assert c.controle_classifieur([b"x"], cfg) is None


@pytest.mark.secteurs_provisoires
@pytest.mark.parametrize("declare", ["Baskuy", "Secteur 30 (Nongr-Massom)", "n'importe quoi", None])
def test_secteur_non_controle_tant_que_la_couche_est_provisoire(sig, ref, cfg, declare):
    """Les vrais noms de secteurs d'un jeu de test externe ne doivent pas être pénalisés par notre couche synthétique."""
    assert cfg.verification.secteurs_officiels is False
    s = {**sig, "secteur": declare} if declare else {k: v for k, v in sig.items() if k != "secteur"}
    r = c.controle_position(s, ref, cfg)
    assert r.etat == c.OK and "provisoire" in r.motif
    # Les impossibilités géométriques restent détectées
    assert c.controle_position({**s, "lat": 0, "lon": 0}, ref, cfg).gravite == c.BLOQUANT
    assert c.controle_position({**s, "lat": 48.85, "lon": 2.35}, ref, cfg).gravite == c.BLOQUANT
