"""Exporte le jeu de signalements de démonstration en GeoJSON, sous licence ouverte (livrable du sujet).

    .venv\\Scripts\\python.exe scripts\\exporter_signalements.py

Ne sort QUE les signalements marqués `synthetique` (jeu fictif demandé par l'organisateur), hors lots d'essai du jury.
Aucune donnée personnelle : ni enquêteur, ni identifiant d'appareil, ni compte, ni code de suivi, ni message vocal, ni photo.
Les identifiants sont renumérotés (S0001...) : ils ne renvoient pas aux identifiants internes de la base.
Sortie : livrables/signalements_synthetiques.geojson
"""
import json
import sqlite3
import sys
from datetime import datetime, timezone
from pathlib import Path

RACINE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RACINE))
from oregdo.verification import base  # noqa: E402

SORTIE = RACINE / "livrables"
LICENCE = {
    "nom": "Open Database License (ODbL) 1.0",
    "url": "https://opendatacommons.org/licenses/odbl/1-0/",
    "attribution": "Orẽgdo, Hackathon des Universités 2026 (jeu de signalements fictif, à des fins de démonstration)",
}
CHAMPS = ("taille", "nature", "caniveau", "accessibilite", "statut", "score", "nb_photos", "source", "secteur")


def main():
    conn = base.ouvrir()
    conn.row_factory = sqlite3.Row
    lignes = conn.execute(
        "SELECT * FROM signalement WHERE synthetique = 1 AND essai = 0 AND lat IS NOT NULL AND lon IS NOT NULL ORDER BY id").fetchall()
    features = []
    for i, r in enumerate(lignes, 1):
        p = {"id": f"S{i:04d}", "date": (r["horodatage"] or r["recu_le"] or "")[:10]}
        for c in CHAMPS:
            v = r[c]
            p[c] = (bool(v) if c == "caniveau" and v is not None else v)
        p["score"] = round(p["score"], 1) if p["score"] is not None else None
        p["synthetique"] = True
        features.append({"type": "Feature", "geometry": {"type": "Point", "coordinates": [round(r["lon"], 6), round(r["lat"], 6)]}, "properties": p})
    sortie = {
        "type": "FeatureCollection",
        "name": "signalements_synthetiques_ouagadougou",
        "description": "Signalements de tas d'ordures FICTIFS pour Ouagadougou (démonstration). Ne pas les prendre pour des observations réelles.",
        "license": LICENCE, "date_export": datetime.now(timezone.utc).strftime("%Y-%m-%d"), "nombre": len(features), "features": features,
    }
    SORTIE.mkdir(exist_ok=True)
    chemin = SORTIE / "signalements_synthetiques.geojson"
    chemin.write_text(json.dumps(sortie, ensure_ascii=False, indent=1), encoding="utf-8")
    par_statut = {}
    for f in features:
        par_statut[f["properties"]["statut"]] = par_statut.get(f["properties"]["statut"], 0) + 1
    print(f"{len(features)} signalements synthétiques exportés vers {chemin} : {par_statut}")


if __name__ == "__main__":
    main()
