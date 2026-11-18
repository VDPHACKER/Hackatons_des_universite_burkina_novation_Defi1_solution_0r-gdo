"""Démarre la plateforme en HTTPS sur le réseau local, pour tester sur un vrai téléphone.

    .venv\\Scripts\\python.exe scripts\\telephone_https.py [--port 8443] [--commune bobo]

Pourquoi : un navigateur de téléphone n'autorise la position GPS, le micro et l'installation de l'application que sur une adresse
SÉCURISÉE (https, ou http://localhost). Avec http://192.168.x.x le bouton « Utiliser ma position » échoue toujours.
Ce script crée un certificat auto-signé pour les adresses de cette machine (data/tls/, valable 30 jours, jamais versionné) puis lance
le serveur. Sur le téléphone : ouvrir l'adresse affichée, accepter l'avertissement du navigateur (« Avancé » puis « Continuer »).
Le téléphone et l'ordinateur doivent être sur le même réseau Wi-Fi, et le pare-feu Windows doit autoriser le port (une fenêtre le demande au 1er lancement).
Limite : le service worker (mode hors ligne) ne s'enregistre pas avec un certificat auto-signé ; pour tester le hors-ligne et l'installation, utiliser
`adb reverse` ou l'option de Chrome décrite dans le README (section « Sur un téléphone »).
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


def certificat(ips):
    TLS.mkdir(parents=True, exist_ok=True)
    cert, cle = TLS / "cert.pem", TLS / "key.pem"
    alt = ",".join(["DNS:localhost", "IP:127.0.0.1"] + [f"IP:{a}" for a in ips])
    subprocess.run([trouver_openssl(), "req", "-x509", "-newkey", "rsa:2048", "-nodes", "-days", "30", "-keyout", str(cle), "-out", str(cert),
                    "-subj", "/CN=oregdo-test", "-addext", f"subjectAltName={alt}"], check=True, capture_output=True)
    return cert, cle


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
    print("\nSur le téléphone (connecté au MÊME Wi-Fi que l'ordinateur), ouvrez cette adresse, puis acceptez l'avertissement du navigateur :")
    if principale in ips:
        print(f"\n    https://{principale}:{a.port}      <-- celle du Wi-Fi, la bonne dans presque tous les cas")
    autres = [ip for ip in ips if ip != principale]
    if autres:
        print("\n  Autres adresses (cartes réseau virtuelles, à n'essayer qu'en dernier recours) :")
        for ip in autres:
            print(f"    https://{ip}:{a.port}")
    print("\nTest rapide : ajoutez /api/sante à l'adresse. Si la page affiche {\"ok\":true, ...}, tout fonctionne.")
    ouvert = regle_pare_feu(a.port)
    if ouvert is False:
        print(f"\n!! Le pare-feu Windows bloque probablement le port {a.port}. Ouvrez PowerShell EN ADMINISTRATEUR et collez :\n"
              f'   New-NetFirewallRule -DisplayName "Oregdo telephone {a.port}" -Direction Inbound -Protocol TCP -LocalPort {a.port} -Action Allow -Profile Private')
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
