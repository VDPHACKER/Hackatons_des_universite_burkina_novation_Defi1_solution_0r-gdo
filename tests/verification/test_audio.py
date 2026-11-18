"""Message vocal joint à un signalement : formats, taille, droits d'écoute, journal d'audit, effacement à l'échéance."""
import base64
from datetime import datetime, timedelta, timezone

import pytest

from oregdo.config import charger_config
from oregdo.verification import audio, base
from outils_photo import photo_neuve
from test_portails import client, compte, entetes  # noqa: F401  (fixture `client` et aides communes)

WEBM = b"\x1a\x45\xdf\xa3" + bytes(range(200)) * 5          # en-tête EBML (WebM) + contenu quelconque


def b64(octets):
    return base64.b64encode(octets).decode()


def deposer(client, sig, **kw):
    return client.post("/api/signalements", json={**sig, **kw})


def dernier_id():
    conn = base.ouvrir()
    sid = conn.execute("SELECT id FROM signalement ORDER BY id DESC").fetchone()[0]
    conn.close()
    return sid


def test_message_vocal_depose_par_un_citoyen_ecoute_par_la_brigade(client, sig):
    compte("agent", "brigade")
    r = deposer(client, sig, audio=b64(WEBM), photos=[b64(photo_neuve())])
    assert r.status_code == 201 and set(r.json()) == {"code_suivi", "statut", "message"}      # le citoyen ne voit ni chemin ni score
    sid = dernier_id()
    ecoute = client.get(f"/api/brigade/audio/{sid}", headers=entetes(client, "agent"))
    assert ecoute.status_code == 200 and ecoute.content == WEBM
    assert ecoute.headers["content-type"] == "audio/webm" and "no-store" in ecoute.headers["cache-control"]
    liste = client.get("/api/signalements", headers=entetes(client, "agent")).json()          # la brigade lit la liste
    ligne = next(s for s in liste["signalements"] if s["id"] == sid)
    assert ligne["a_audio"] is True and "audio" not in ligne                                  # on n'expose que la présence


def test_l_ecoute_est_reservee_et_journalisee(client, sig):
    compte("agent", "brigade")
    compte("awa", "precollecteur")
    compte("chef", "admin")
    deposer(client, sig, audio=b64(WEBM))
    sid = dernier_id()
    url = f"/api/brigade/audio/{sid}"
    assert client.get(url).status_code == 401                                                # sans compte
    assert client.get(url, headers=entetes(client, "awa")).status_code == 403                # un enquêteur n'écoute pas les voix
    assert client.get(url, headers=entetes(client, "agent")).status_code == 200
    evenements = client.get("/api/admin/audit?limite=20", headers=entetes(client, "chef")).json()["evenements"]
    assert any(e["action"] == "ecoute_message_vocal" and e["cible"] == str(sid) and e["utilisateur"] == "agent" for e in evenements)


@pytest.mark.parametrize("brut", [b"ceci n'est pas de l'audio" * 10, b"\x89PNG\r\n\x1a\n" + bytes(300)])      # texte, image déguisée
def test_formats_invalides_refuses(client, sig, brut):
    r = deposer(client, sig, audio=b64(brut))
    assert r.status_code == 422 and "Format audio non reconnu" in r.json()["detail"]


def test_trop_volumineux_ou_mal_encode_refuse(client, sig):
    mx = charger_config().verification.audio.octets_max
    assert deposer(client, sig, audio=b64(b"\x1a\x45\xdf\xa3" + bytes(mx))).status_code == 422
    assert deposer(client, sig, audio="%%% pas du base64 %%%").status_code == 422
    conn = base.ouvrir()
    assert conn.execute("SELECT COUNT(*) FROM signalement").fetchone()[0] == 0                # un refus n'enregistre rien
    conn.close()


def test_data_url_et_trois_formats_acceptes(client, sig, bons_points):
    for i, brut in enumerate((WEBM, b"OggS" + bytes(300), bytes(4) + b"ftypM4A " + bytes(300))):
        autre = {**sig, **bons_points[i + 1], "appareil": f"A{i}", "enqueteur": f"E{i}"}
        assert deposer(client, autre, audio="data:audio/webm;base64," + b64(brut)).status_code == 201
    conn = base.ouvrir()
    assert sorted(r[0].split(".")[1] for r in conn.execute("SELECT audio FROM signalement")) == ["m4a", "ogg", "webm"]
    conn.close()


def test_effacement_a_echeance_garde_le_signalement(client, sig):
    compte("agent", "brigade")
    deposer(client, sig, audio=b64(WEBM))
    sid = dernier_id()
    cfg = charger_config()
    conn = base.ouvrir()
    fichier = audio.chemin(conn, sid)[0]
    assert fichier.exists()
    assert audio.purger(conn, cfg) == 0                                                      # trop récent : rien n'est effacé
    futur = datetime.now(timezone.utc) + timedelta(days=cfg.verification.audio.conservation_jours + 1)
    assert audio.purger(conn, cfg, maintenant=futur) == 1
    assert not fichier.exists() and audio.chemin(conn, sid) is None
    assert base.lire_signalement(conn, sid) is not None                                      # le signalement, lui, reste (règle du projet)
    conn.close()
    assert client.get(f"/api/brigade/audio/{sid}", headers=entetes(client, "agent")).status_code == 404


def test_cinq_photos_acceptees_six_refusees(client, sig):
    photos = [b64(photo_neuve()) for _ in range(5)]
    assert deposer(client, sig, photos=photos).status_code == 201
    r = deposer(client, {**sig, "appareil": "AUTRE"}, photos=photos + [photos[0]])
    assert r.status_code == 422 and "maximum 5" in r.json()["detail"]
