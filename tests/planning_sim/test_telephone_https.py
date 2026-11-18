"""Autorité de certification locale du lanceur téléphone (scripts/telephone_https.py) : https valide sur le Wi-Fi, sans Internet."""
import importlib.util
import subprocess
from pathlib import Path

import pytest

RACINE = Path(__file__).resolve().parents[2]


@pytest.fixture(scope="module")
def lanceur(tmp_path_factory):
    spec = importlib.util.spec_from_file_location("telephone_https", RACINE / "scripts" / "telephone_https.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    try:
        mod.ossl = mod.trouver_openssl()
    except SystemExit:
        pytest.skip("openssl absent (installer Git pour Windows)")
    mod.TLS = tmp_path_factory.mktemp("tls")
    return mod


def _verifier(ossl, ca, cert):
    return subprocess.run([ossl, "verify", "-CAfile", str(ca), str(cert)], capture_output=True, text=True)


def test_le_certificat_du_serveur_est_signe_par_l_autorite_locale(lanceur):
    cert, cle = lanceur.certificat(["192.168.1.20"])
    ca = lanceur.TLS / lanceur.NOM_CERTIFICAT_AUTORITE
    r = _verifier(lanceur.ossl, ca, cert)
    assert r.returncode == 0, r.stdout + r.stderr
    texte = subprocess.run([lanceur.ossl, "x509", "-in", str(cert), "-noout", "-text"], capture_output=True, text=True).stdout
    assert "192.168.1.20" in texte and "TLS Web Server Authentication" in texte
    assert b"PRIVATE KEY" not in ca.read_bytes()                     # le fichier proposé au téléphone ne contient jamais la clé


def test_l_autorite_est_reutilisee_d_un_lancement_a_l_autre(lanceur):
    lanceur.certificat(["10.0.0.4"])
    avant = (lanceur.TLS / lanceur.NOM_CERTIFICAT_AUTORITE).read_bytes()
    lanceur.certificat(["10.0.0.5"])
    apres = (lanceur.TLS / lanceur.NOM_CERTIFICAT_AUTORITE).read_bytes()
    assert avant == apres                                             # un téléphone déjà équipé n'a rien à refaire


def test_l_autorite_ne_peut_pas_signer_pour_une_adresse_d_internet(lanceur):
    """Contrainte de noms : même si la clé de l'autorité fuyait, elle ne servirait pas à imiter un site public."""
    ca_crt, ca_cle = lanceur.autorite()
    d = lanceur.TLS
    (d / "pub.ext").write_text("subjectAltName=IP:8.8.8.8\nextendedKeyUsage=serverAuth\n", encoding="ascii")
    subprocess.run([lanceur.ossl, "req", "-new", "-newkey", "rsa:2048", "-nodes", "-keyout", str(d / "pub.key"), "-out", str(d / "pub.csr"),
                    "-subj", "/CN=faux"], check=True, capture_output=True)
    subprocess.run([lanceur.ossl, "x509", "-req", "-in", str(d / "pub.csr"), "-CA", str(ca_crt), "-CAkey", str(ca_cle), "-CAcreateserial",
                    "-days", "30", "-extfile", str(d / "pub.ext"), "-out", str(d / "pub.pem")], check=True, capture_output=True)
    r = _verifier(lanceur.ossl, ca_crt, d / "pub.pem")
    assert r.returncode != 0 and "permitted subtree violation" in (r.stdout + r.stderr)
