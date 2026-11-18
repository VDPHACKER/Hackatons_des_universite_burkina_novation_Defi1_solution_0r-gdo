#!/bin/sh
# Entrée du conteneur : prépare les données et l'administrateur (mot de passe aléatoire affiché une fois), puis démarre le serveur.
set -e
python scripts/premier_demarrage.py
exec uvicorn oregdo.app:app --host 0.0.0.0 --port 8000
