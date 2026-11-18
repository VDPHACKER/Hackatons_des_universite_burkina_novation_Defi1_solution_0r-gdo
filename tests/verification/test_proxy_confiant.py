"""Adresse du client derrière un proxy ou un tunnel : l'en-tête transmis n'est cru que si on l'a explicitement autorisé."""
from starlette.requests import Request

from oregdo import securite


def requete(entetes: dict, hote="127.0.0.1"):
    scope = {"type": "http", "method": "POST", "path": "/", "headers": [(k.lower().encode(), v.encode()) for k, v in entetes.items()],
             "client": (hote, 5000), "query_string": b""}
    return Request(scope)


def test_par_defaut_l_en_tete_du_proxy_est_ignore(monkeypatch):
    monkeypatch.delenv("OREGDO_PROXY_CONFIANT", raising=False)
    r = requete({"CF-Connecting-IP": "203.0.113.9", "X-Forwarded-For": "198.51.100.7"})
    assert securite.ip_client(r) == "127.0.0.1"                      # sinon n'importe qui pourrait choisir son adresse et contourner la limite


def test_derriere_un_proxy_de_confiance_chaque_visiteur_a_sa_propre_adresse(monkeypatch):
    monkeypatch.setenv("OREGDO_PROXY_CONFIANT", "1")
    assert securite.ip_client(requete({"CF-Connecting-IP": "203.0.113.9"})) == "203.0.113.9"
    assert securite.ip_client(requete({"X-Forwarded-For": "198.51.100.7, 10.0.0.1"})) == "198.51.100.7"
    assert securite.ip_client(requete({})) == "127.0.0.1"             # pas d'en-tête : on retombe sur l'adresse de la connexion


def test_la_limitation_est_par_visiteur_et_non_pour_tout_le_tunnel(monkeypatch):
    monkeypatch.setenv("OREGDO_PROXY_CONFIANT", "1")
    a = securite.ip_client(requete({"CF-Connecting-IP": "203.0.113.1"}))
    b = securite.ip_client(requete({"CF-Connecting-IP": "203.0.113.2"}))
    assert a != b
