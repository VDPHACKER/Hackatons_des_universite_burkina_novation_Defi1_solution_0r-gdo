"""Collecte de terrain simulée (demandée par le jury) et règle de précision GPS qu'elle a fait apparaître."""
import pytest

from oregdo.config import charger_config
from oregdo.verification import base, collecte_simulee as cs, controles, importation, score


@pytest.fixture(scope="module")
def campagne(tmp_path_factory):
    cfg, ref = charger_config(), controles.reference()
    sec, tas, sorties = cs.simuler(graine=7, n_tas=12)
    conn = base.ouvrir(tmp_path_factory.mktemp("cs") / "c.db")
    bilan = cs.evaluer(conn, tas, sorties, cfg, ref)
    conn.close()
    return sec, tas, sorties, bilan


def test_la_campagne_est_reproductible_et_reste_dans_le_secteur(campagne):
    sec, tas, sorties, _ = campagne
    sec2, tas2, sorties2 = cs.simuler(graine=7, n_tas=12)
    assert [t["id"] for t in tas] == [t["id"] for t in tas2] and len(sorties) == len(sorties2)
    assert all(sec.geometry.buffer(0.0005).covers(__import__("shapely.geometry", fromlist=["Point"]).Point(t["lon"], t["lat"])) for t in tas)
    assert {s["sig"]["enqueteur"] for s in sorties} <= set(cs.EQUIPE)


def test_le_pipeline_retrouve_les_tas_sans_faux_depotoir(campagne):
    _, _, _, b = campagne
    assert b["tas_retrouves"] >= 0.7 * b["tas_signales"]          # la plupart des tas vus deviennent des dépotoirs vérifiés
    assert b["faux_depotoirs"] == 0                               # un mauvais GPS ne crée plus de faux tas
    assert b["fusionnes_en_un"] == b["tas_vus_par_deux_membres"]  # deux membres sur un même tas : un seul dépotoir
    assert b["erreur_position_m"] < 15


def test_precision_gps_insuffisante_plafonne_a_confirmer(sig, cfg, ref):
    from oregdo.verification.synthetique import exif_fictif, photo_synthetique
    from datetime import datetime, timezone
    photo = photo_synthetique(5, exif=exif_fictif(sig["lat"], sig["lon"], datetime.now(timezone.utc)))
    histo = []
    bon, _, _ = score.evaluer({**sig, "precision_m": 12}, [controles.analyser_photo(photo)], histo, set(), ref, cfg)
    s, statut, res = score.evaluer({**sig, "precision_m": 180}, [controles.analyser_photo(photo)], histo, set(), ref, cfg)
    assert statut != "verifie" and any(r.controle == score.REGLE_GPS_IMPRECIS for r in res)
    assert bon > s


def test_la_precision_du_geopoint_kobo_est_lue_a_l_import():
    lignes, refus, err = importation.lire_csv("geopoint,username\n12.3714 -1.5197 305 150,BN-M1\n")
    assert err is None and not refus
    assert importation._normaliser(lignes[0][1], "csv")["precision_m"] == 150
