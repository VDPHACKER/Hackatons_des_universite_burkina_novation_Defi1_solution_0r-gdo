"""Premier démarrage : prépare le dossier de données et crée l'administrateur s'il n'existe pas encore.

Appelé par `scripts/deployer.ps1` (Windows) et par l'entrée Docker. Jamais de mot de passe par défaut :
- si OREGDO_ADMIN_MDP est défini, le serveur crée l'administrateur lui-même au démarrage (rien à faire ici) ;
- sinon, un mot de passe ALÉATOIRE est généré, affiché UNE SEULE FOIS ici, et seul son hachage (scrypt) est stocké.
"""
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from oregdo import comptes  # noqa: E402
from oregdo.verification import base  # noqa: E402


def main() -> int:
    conn = base.ouvrir()                                   # crée data/ et la base (schéma à jour) si besoin
    try:
        if conn.execute("SELECT 1 FROM utilisateur WHERE role='admin' AND actif=1 LIMIT 1").fetchone():
            print("Administrateur déjà présent : rien à créer.")
            return 0
        if os.environ.get("OREGDO_ADMIN_MDP"):
            print("Administrateur créé au démarrage du serveur depuis OREGDO_ADMIN_ID / OREGDO_ADMIN_MDP.")
            return 0
        ident, mdp = os.environ.get("OREGDO_ADMIN_ID", "admin"), comptes.mot_de_passe_lisible()      # lisible : se recopie sans erreur
        comptes.creer_utilisateur(conn, ident, "Administration", "admin", mdp)
        print("=" * 66)
        print("  Premier démarrage : compte administrateur créé.")
        print(f"  Identifiant  : {ident}")
        print(f"  Mot de passe : {mdp}")
        print("  Notez-le maintenant : il ne sera plus jamais affiché.")
        print("  Perdu ? python -m oregdo.comptes reinitialiser --id " + ident)
        print("  Comptes de démonstration (un par rôle) : double-cliquer scripts\\comptes.bat")
        print("=" * 66)
        return 0
    finally:
        conn.close()


if __name__ == "__main__":
    sys.exit(main())
