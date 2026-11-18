"""Comptes faciles à obtenir et à saisir : un compte par rôle en une commande, mot de passe perdu réinitialisé,
identifiant tapé avec une majuscule (clavier de téléphone) accepté."""
import pytest

from oregdo import comptes, securite
from oregdo.verification import base


@pytest.fixture
def conn(tmp_path, monkeypatch):
    monkeypatch.setenv("OREGDO_DB", str(tmp_path / "comptes.db"))
    c = base.ouvrir()
    yield c
    c.close()


def test_un_compte_par_role_en_une_commande_et_chacun_se_connecte(conn):
    lignes = comptes.comptes_demo(conn)
    assert {r for _, r, _ in lignes} == set(securite.ROLES)
    for ident, role, mdp in lignes:
        assert comptes.connecter(conn, ident, mdp)["utilisateur"]["role"] == role


def test_la_commande_relancee_remet_les_comptes_a_zero_avec_un_mot_de_passe_commun(conn):
    comptes.comptes_demo(conn)
    for _ in range(5):
        with pytest.raises(comptes.ErreurCompte):
            comptes.connecter(conn, "mairie", "faux-mot-de-passe")            # jusqu'au blocage du compte
    comptes.comptes_demo(conn, "equipe-oregdo-2026")
    assert comptes.connecter(conn, "mairie", "equipe-oregdo-2026")          # débloqué, nouveau mot de passe
    assert conn.execute("SELECT COUNT(*) FROM utilisateur").fetchone()[0] == len(securite.ROLES)


def test_mot_de_passe_lisible(conn):
    mdp = comptes.mot_de_passe_lisible()
    assert len(mdp) >= 8 and mdp.count("-") >= 3 and mdp == mdp.lower() and not set(mdp) & set("01OI")
    securite.valider_mot_de_passe(mdp)


def test_identifiant_avec_majuscule_et_espaces_accepte(conn):
    comptes.creer_utilisateur(conn, "admin", "Administration", "admin", "kaya-vert-soleil-47")
    assert comptes.connecter(conn, " Admin ", "kaya-vert-soleil-47")["utilisateur"]["identifiant"] == "admin"
    assert comptes.connecter(conn, "ADMIN", "kaya-vert-soleil-47 ")            # espace ajoutée par le clavier
    assert comptes.connecter(conn, "admin", "kaya–vert—soleil-47")             # tirets transformés par le téléphone
    with pytest.raises(comptes.ErreurCompte):
        comptes.creer_utilisateur(conn, "Admin", "Doublon", "admin", "kaya-vert-soleil-47")   # pas de doublon à la casse près


def test_reinitialiser_un_compte_perdu_et_bloque(conn):
    comptes.creer_utilisateur(conn, "admin", "Administration", "admin", "ancien-mot-de-passe")
    for _ in range(5):
        with pytest.raises(comptes.ErreurCompte):
            comptes.connecter(conn, "admin", "faux")
    comptes.modifier_utilisateur(conn, "admin", actif=False)
    nouveau = comptes.reinitialiser(conn, "ADMIN")
    assert comptes.connecter(conn, "admin", nouveau)["utilisateur"]["actif"]
