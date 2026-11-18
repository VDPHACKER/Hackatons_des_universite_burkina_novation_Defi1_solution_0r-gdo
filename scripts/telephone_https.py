"""Démarre la plateforme en HTTPS sur le réseau local, pour tester sur un vrai téléphone.

    .venv\\Scripts\\python.exe scripts\\telephone_https.py [--port 8443] [--commune bobo]

Pourquoi : un navigateur de téléphone n'autorise la position GPS, le micro et l'installation de l'application que sur une adresse
SÉCURISÉE (https, ou http://localhost). Avec http://192.168.x.x le bouton « Utiliser ma position » échoue toujours.
https ne demande pas Internet : c'est un chiffrement entre le téléphone et cet ordinateur, sur le Wi-Fi local.
Ce script crée une AUTORITÉ DE CERTIFICATION LOCALE (une fois, dans data/tls/, jamais versionné), signe avec elle un certificat pour les
adresses de cette machine, sert une petite page d'installation en http (port 8444), puis lance le serveur en https (port 8443).
Chaque téléphone installe UNE FOIS le certificat de l'autorité depuis cette page ; ensuite l'adresse https s'ouvre sans avertissement et
le GPS, le micro, l'installation de l'application et le mode hors ligne fonctionnent, sans Internet.
L'autorité est limitée aux adresses privées et à localhost : elle ne peut pas servir à imiter un site d'Internet.
Le téléphone et l'ordinateur doivent être sur le même réseau Wi-Fi, et le pare-feu Windows doit autoriser les deux ports.
"""
import argparse
import ipaddress
import os
import shutil
import socket
import subprocess
import sys
from pathlib import Path

RACINE = Path(__file__).resolve().parents[1]
TLS = RACINE / "data" / "tls"


def trouver_openssl():
    chemin = shutil.which("openssl")
    if chemin:
        return chemin
    git = shutil.which("git")                       # Git pour Windows embarque openssl
    if git:
        candidat = Path(git).resolve().parents[1] / "usr" / "bin" / "openssl.exe"
        if candidat.exists():
            return str(candidat)
    sys.exit("openssl introuvable : installez Git pour Windows (il en contient un) ou ajoutez openssl au PATH.")


def adresse_principale():
    """L'adresse que l'ordinateur utilise pour sortir sur le réseau : presque toujours celle du Wi-Fi, donc la seule utile au téléphone."""
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
            s.connect(("10.255.255.255", 1))
            return s.getsockname()[0]
    except OSError:
        return None


def port_libre(depart):
    """Premier port libre à partir de `depart` : un ancien serveur resté en arrière-plan ne bloque plus le lancement."""
    for p in range(depart, depart + 20):
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            if s.connect_ex(("127.0.0.1", p)) != 0:
                return p
    sys.exit(f"Aucun port libre entre {depart} et {depart + 19} : fermez les anciennes fenêtres du serveur.")


def regle_pare_feu(port):
    """True si une règle entrante autorise ce port (lecture seule, sans droits d'administrateur), None si on ne peut pas le savoir."""
    try:
        r = subprocess.run(["netsh", "advfirewall", "firewall", "show", "rule", "name=all", "dir=in", "status=enabled"], capture_output=True, text=True, timeout=20, errors="replace")
    except (OSError, subprocess.SubprocessError):
        return None
    if r.returncode != 0:
        return None
    texte = r.stdout
    return f"{port}" in texte


def adresses_locales():
    """Adresses IPv4 privées de cette machine (celles que le téléphone peut joindre)."""
    trouvees = set()
    try:
        trouvees.update(socket.gethostbyname_ex(socket.gethostname())[2])
    except OSError:
        pass
    try:                                            # l'adresse utilisée pour sortir sur le réseau (souvent le Wi-Fi)
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
            s.connect(("10.255.255.255", 1))
            trouvees.add(s.getsockname()[0])
    except OSError:
        pass
    return sorted(a for a in trouvees if ipaddress.ip_address(a).is_private and not a.startswith("127."))


# Autorité de certification LOCALE : créée une fois, gardée dans data/tls/ (jamais versionné), installée une fois sur chaque téléphone.
# Elle est limitée aux adresses privées et à localhost (nameConstraints) : même si sa clé fuyait, elle ne pourrait pas imiter un site d'Internet.
CONTRAINTES = ",".join(["critical"] + [f"permitted;IP:{r}" for r in ("10.0.0.0/255.0.0.0", "172.16.0.0/255.240.0.0", "192.168.0.0/255.255.0.0",
                                                                     "127.0.0.0/255.0.0.0")] + ["permitted;DNS:localhost"])
NOM_CERTIFICAT_AUTORITE = "oregdo-autorite-locale.crt"


def autorite():
    """Clé et certificat de l'autorité locale (10 ans). Réutilisés à chaque lancement : le téléphone ne l'installe qu'une fois."""
    TLS.mkdir(parents=True, exist_ok=True)
    cle, crt = TLS / "autorite.key", TLS / NOM_CERTIFICAT_AUTORITE
    if not (cle.exists() and crt.exists()):
        subprocess.run([trouver_openssl(), "req", "-x509", "-newkey", "rsa:2048", "-nodes", "-sha256", "-days", "3650",
                        "-keyout", str(cle), "-out", str(crt), "-subj", "/O=Oregdo/CN=Oregdo autorite locale (reseau prive)",
                        "-addext", "basicConstraints=critical,CA:TRUE,pathlen:0",
                        "-addext", "keyUsage=critical,keyCertSign,cRLSign",
                        "-addext", f"nameConstraints={CONTRAINTES}"], check=True, capture_output=True)
    return crt, cle


def certificat(ips):
    """Certificat du serveur signé par l'autorité locale, pour les adresses actuelles de la machine (régénéré à chaque lancement).
    397 jours au plus et usage « serveur » : ce sont les règles d'Android et d'iOS pour qu'un certificat soit accepté sans avertissement."""
    ca_crt, ca_cle = autorite()
    cert, cle, demande, ext = TLS / "cert.pem", TLS / "key.pem", TLS / "serveur.csr", TLS / "serveur.ext"
    alt = ",".join(["DNS:localhost", "IP:127.0.0.1"] + [f"IP:{a}" for a in ips])
    ext.write_text(f"subjectAltName={alt}\nbasicConstraints=critical,CA:FALSE\nkeyUsage=critical,digitalSignature,keyEncipherment\n"
                   "extendedKeyUsage=serverAuth\n", encoding="ascii")
    ossl = trouver_openssl()
    subprocess.run([ossl, "req", "-new", "-newkey", "rsa:2048", "-nodes", "-keyout", str(cle), "-out", str(demande),
                    "-subj", "/O=Oregdo/CN=Oregdo serveur local"], check=True, capture_output=True)
    subprocess.run([ossl, "x509", "-req", "-in", str(demande), "-CA", str(ca_crt), "-CAkey", str(ca_cle), "-CAcreateserial",
                    "-days", "397", "-sha256", "-extfile", str(ext), "-out", str(cert)], check=True, capture_output=True)
    demande.unlink(missing_ok=True)
    return cert, cle


PAGE_INSTALLATION = """<!doctype html><html lang="fr"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Orẽgdo : installer le certificat</title><style>body{{font-family:system-ui,sans-serif;max-width:640px;margin:0 auto;padding:16px;line-height:1.5;color:#14281c}}
a.btn{{display:block;text-align:center;background:#1e7a46;color:#fff;padding:14px;border-radius:10px;text-decoration:none;font-weight:700;margin:16px 0}}
h2{{font-size:1.1rem;margin-top:24px}}code{{background:#eef3ee;padding:2px 4px;border-radius:4px}}</style></head><body>
<h1>Orẽgdo sur ce téléphone</h1>
<p>Une seule fois par téléphone : installez le certificat de l'ordinateur de la mairie. Ensuite, l'application s'ouvre en https sans avertissement,
et le GPS, le micro, l'installation et le <b>mode hors ligne</b> fonctionnent, sans Internet.</p>
<a class="btn" href="/{nom}">1. Télécharger le certificat</a>
<h2>2. Android</h2>
<p>Paramètres, puis Sécurité (ou « Sécurité et confidentialité »), puis « Chiffrement et identifiants » (ou « Autres paramètres de sécurité »),
puis « Installer un certificat », puis « Certificat CA ». Choisissez le fichier <code>{nom}</code> dans Téléchargements et confirmez.</p>
<h2>2. iPhone</h2>
<p>Ouvrez cette page dans Safari et touchez « Télécharger », puis « Autoriser ». Dans Réglages, touchez « Profil téléchargé » et « Installer ».
Enfin, dans Réglages, Général, Informations, « Réglages des certificats », activez la confiance pour « Oregdo autorite locale ».</p>
<h2>3. Ouvrir l'application</h2>
<p><a href="https://{ip}:{port}/">https://{ip}:{port}/</a> : il ne doit plus y avoir d'avertissement. Ouvrez la page d'accueil une fois ;
elle reste ensuite disponible sans réseau.</p>
<p style="color:#4a5e51;font-size:.9rem">Ce certificat ne vaut que pour les adresses du réseau local (192.168.x.x, 10.x.x.x, 172.16 à 31.x.x) :
il ne permet pas d'intercepter les sites d'Internet.</p></body></html>"""


def servir_installation(port_https, ip, port):
    """Petite page en http (port 8444 par défaut) : le téléphone y télécharge le certificat de l'autorité avant de passer en https.
    Elle ne sert que deux contenus : la page d'explication et le certificat PUBLIC de l'autorité (jamais sa clé)."""
    import threading
    from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
    crt = (TLS / NOM_CERTIFICAT_AUTORITE).read_bytes()
    page = PAGE_INSTALLATION.format(nom=NOM_CERTIFICAT_AUTORITE, ip=ip, port=port_https).encode("utf-8")

    class Gestion(BaseHTTPRequestHandler):
        def do_GET(self):
            if self.path == "/" + NOM_CERTIFICAT_AUTORITE:
                corps, type_ = crt, "application/x-x509-ca-cert"
            elif self.path in ("/", "/index.html"):
                corps, type_ = page, "text/html; charset=utf-8"
            else:
                self.send_error(404); return
            self.send_response(200)
            self.send_header("Content-Type", type_)
            self.send_header("Content-Length", str(len(corps)))
            self.end_headers()
            self.wfile.write(corps)

        def log_message(self, *args):          # pas de journal des visites dans la console
            pass

    serveur = ThreadingHTTPServer(("0.0.0.0", port), Gestion)
    threading.Thread(target=serveur.serve_forever, name="installation-certificat", daemon=True).start()
    return serveur


def main():
    sys.stdout.reconfigure(line_buffering=True, encoding="utf-8", errors="replace")      # le texte s'affiche tout de suite, même si la sortie est redirigée
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--port", type=int, default=8443, help="port souhaité ; s'il est occupé, le suivant est pris")
    ap.add_argument("--commune", help="code du pack à servir (défaut : variable OREGDO_COMMUNE ou ouaga)")
    a = ap.parse_args()
    ips = adresses_locales()
    if not ips:
        sys.exit("Aucune adresse réseau privée trouvée : connectez l'ordinateur au Wi-Fi.")
    cert, cle = certificat(ips)
    demande, a.port = a.port, port_libre(a.port)
    if a.port != demande:
        print(f"\nLe port {demande} est déjà utilisé (ancien serveur resté ouvert ?) : le port {a.port} est utilisé à la place.")
    principale = adresse_principale()
    ip_wifi = principale if principale in ips else ips[0]
    port_install = port_libre(a.port + 1)
    if port_install == a.port:
        port_install = port_libre(a.port + 2)
    servir_installation(a.port, ip_wifi, port_install)
    print("\nSur le téléphone, connecté au MÊME Wi-Fi que l'ordinateur (Internet n'est pas nécessaire) :")
    print(f"\n  1. UNE SEULE FOIS par téléphone, installer le certificat :   http://{ip_wifi}:{port_install}")
    print(f"  2. Ouvrir l'application, sans avertissement :                https://{ip_wifi}:{a.port}")
    print("     (GPS, micro, installation de l'application et mode hors ligne fonctionnent.)")
    autres = [ip for ip in ips if ip != ip_wifi]
    if autres:
        print("\n  Autres adresses (cartes réseau virtuelles, à n'essayer qu'en dernier recours) : " + ", ".join(autres))
    print("\nTest rapide : ajoutez /api/sante à l'adresse https. Si la page affiche {\"ok\":true, ...}, tout fonctionne.")
    print(f"Le certificat de l'autorité est gardé dans {TLS} : les téléphones déjà équipés n'ont rien à refaire au prochain lancement.")
    ouvert = regle_pare_feu(a.port)
    if ouvert is False or regle_pare_feu(port_install) is False:
        print(f"\n!! Le pare-feu Windows bloque probablement les ports {a.port} et {port_install}. Ouvrez PowerShell EN ADMINISTRATEUR et collez :\n"
              f'   New-NetFirewallRule -DisplayName "Oregdo telephone" -Direction Inbound -Protocol TCP -LocalPort {a.port},{port_install} -Action Allow -Profile Private')
    elif ouvert is None:
        print(f"\n(Le pare-feu n'a pas pu être vérifié. Si le téléphone n'arrive pas à se connecter, autorisez le port {a.port}  : voir le README, section « Sur un téléphone ».)")
    print("\nCtrl+C pour arrêter.\n")
    env = dict(os.environ)
    if a.commune:
        env["OREGDO_COMMUNE"] = a.commune
    os.chdir(RACINE)
    subprocess.run([sys.executable, "-m", "uvicorn", "oregdo.app:app", "--host", "0.0.0.0", "--port", str(a.port),
                    "--ssl-keyfile", str(cle), "--ssl-certfile", str(cert)], env=env)


if __name__ == "__main__":
    main()
