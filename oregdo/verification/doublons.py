"""Regroupement des signalements validés d'un même tas en un dépotoir (DBSCAN), confiance et export OSM.

Règle : dix signalements du même tas = UN dépotoir. La confiance monte avec le nombre d'enquêteurs
DISTINCTS, jamais avec le nombre de signalements (un même enquêteur ou un même appareil qui répète
ne gonfle rien).
"""
import xml.etree.ElementTree as ET
from collections import defaultdict

import numpy as np
from sklearn.cluster import DBSCAN

from . import base

RAYON_TERRE_M = 6371008.8


def regrouper(points, rayon_m, min_echantillons=1) -> list[int]:
    """Étiquette de groupe pour chaque point (lat, lon) : DBSCAN, distance haversine, rayon en mètres."""
    if not points:
        return []
    rad = np.radians(np.array(points, dtype=float))
    return DBSCAN(eps=rayon_m / RAYON_TERRE_M, min_samples=min_echantillons,
                  metric="haversine", algorithm="ball_tree").fit(rad).labels_.tolist()


def consolider(conn, cfg) -> int:
    """Recalcule les dépotoirs à partir des signalements « vérifiés ». Renvoie le nombre de dépotoirs actifs."""
    v = cfg.verification
    lignes = [dict(r) for r in conn.execute(
        "SELECT * FROM signalement WHERE statut='verifie' AND essai=0 AND lat IS NOT NULL AND lon IS NOT NULL ORDER BY id")]
    etiquettes = regrouper([(r["lat"], r["lon"]) for r in lignes], v.doublons.rayon_m, v.doublons.min_echantillons)
    groupes = defaultdict(list)
    for r, e in zip(lignes, etiquettes):
        groupes[e].append(r)
    conn.execute("UPDATE signalement SET depotoir_id=NULL")
    utilises = set()
    for membres in groupes.values():
        enqueteurs = {m["enqueteur"] or m["appareil"] for m in membres if (m["enqueteur"] or m["appareil"])}
        n_dist = max(1, len(enqueteurs))
        confiance = min(100.0, max(m["score"] for m in membres) + v.corroboration.bonus_points * (n_dist - 1))
        lat = sum(m["lat"] for m in membres) / len(membres)
        lon = sum(m["lon"] for m in membres) / len(membres)
        synth = int(all(m["synthetique"] for m in membres))
        # On garde l'identifiant d'un dépotoir déjà connu pour que les identifiants restent stables.
        existant = next((m["depotoir_id"] for m in membres if m["depotoir_id"] and m["depotoir_id"] not in utilises), None)
        valeurs = (lat, lon, len(membres), n_dist, round(confiance, 1), "verifie", synth, base.maintenant())
        if existant:
            conn.execute("UPDATE depotoir SET lat=?, lon=?, nb_signalements=?, nb_enqueteurs=?, confiance=?, statut=?, "
                         "synthetique=?, mis_a_jour_le=? WHERE id=?", (*valeurs, existant))
            did = existant
        else:
            did = conn.execute("INSERT INTO depotoir (lat, lon, nb_signalements, nb_enqueteurs, confiance, statut, "
                               "synthetique, mis_a_jour_le) VALUES (?,?,?,?,?,?,?,?)", valeurs).lastrowid
        utilises.add(did)
        conn.executemany("UPDATE signalement SET depotoir_id=? WHERE id=?", [(did, m["id"]) for m in membres])
    # Un dépotoir qui n'a plus aucun signalement validé est conservé mais marqué comme tel.
    marques = ",".join(str(i) for i in utilises) or "0"
    conn.execute(f"UPDATE depotoir SET statut='sans_signalement_valide', nb_signalements=0, nb_enqueteurs=0, confiance=0 "
                 f"WHERE id NOT IN ({marques})")
    conn.commit()
    return len(utilises)


class ExportSynthetiqueRefuse(Exception):
    """Levée quand on demande l'export OSM de dépotoirs synthétiques sans l'autorisation explicite `demo`."""


def lister_depotoirs(conn, statut="verifie") -> dict:
    """Dépotoirs consolidés au format GeoJSON (points) avec la confiance et l'indicateur `synthetique`."""
    rows = conn.execute("SELECT * FROM depotoir WHERE statut=? ORDER BY id", (statut,)).fetchall()
    feats = []
    for r in rows:
        props = {k: r[k] for k in r.keys() if k not in ("lat", "lon")}
        props["synthetique"] = bool(r["synthetique"])
        feats.append({"type": "Feature", "geometry": {"type": "Point", "coordinates": [r["lon"], r["lat"]]}, "properties": props})
    return {"type": "FeatureCollection", "synthetique": any(f["properties"]["synthetique"] for f in feats),
            "nb_synthetiques": sum(f["properties"]["synthetique"] for f in feats), "features": feats}


def _tags(d, tags_base, demo, cfg):
    """Tags OSM standards : ceux de la config + note, check_date, fixme (pas de clé inventée)."""
    note = f"Dépotoir sauvage signalé par {d['nb_enqueteurs']} enquêteur(s) distinct(s), confiance {d['confiance']:.0f}/100 (Orẽgdo)."
    tags = {**{k: str(v) for k, v in tags_base.items()}, "note": note,
            "check_date": str(d["mis_a_jour_le"])[:10], "fixme": "À confirmer sur place avant import ; voir " + cfg.export_osm.note}
    if demo:
        tags["note"] = "DÉMONSTRATION : données synthétiques, NE PAS VERSER DANS OSM. " + note
    return tags


def export_osm(conn, cfg, demo=False) -> dict:
    """Export des seuls dépotoirs vérifiés : GeoJSON et fichier .osm (JOSM), tags pris dans la config.
    Les dépotoirs synthétiques ne sortent que si `demo` est vrai (avec une note de démonstration)."""
    tags_base = vars(cfg.export_osm.tags_depotoir_sauvage)
    tous = conn.execute("SELECT * FROM depotoir WHERE statut='verifie' ORDER BY id").fetchall()
    synth = [d for d in tous if d["synthetique"]]
    depots = tous if demo else [d for d in tous if not d["synthetique"]]
    if synth and not depots and not demo:
        raise ExportSynthetiqueRefuse(f"Export refusé : les {len(synth)} dépotoir(s) vérifié(s) sont synthétiques (données de démonstration). "
                                      "Versés dans OpenStreetMap, ils le pollueraient. Ajoutez ?demo=1 pour un fichier de démonstration clairement marqué.")
    geojson = {"type": "FeatureCollection", "note": cfg.export_osm.note, "demo": bool(demo and synth), "features": [
        {"type": "Feature", "geometry": {"type": "Point", "coordinates": [d["lon"], d["lat"]]},
         "properties": _tags(d, tags_base, demo and d["synthetique"], cfg)} for d in depots]}
    racine = ET.Element("osm", version="0.6", generator="Orẽgdo")
    if demo and synth:
        racine.append(ET.Comment(" DEMONSTRATION : donnees synthetiques, ne pas verser dans OpenStreetMap "))
    for i, d in enumerate(depots, 1):
        noeud = ET.SubElement(racine, "node", id=str(-i), lat=f"{d['lat']:.7f}", lon=f"{d['lon']:.7f}", action="modify", visible="true")
        for k, val in _tags(d, tags_base, demo and d["synthetique"], cfg).items():
            ET.SubElement(noeud, "tag", k=str(k), v=str(val)[:255])
    xml = '<?xml version="1.0" encoding="UTF-8"?>\n' + ET.tostring(racine, encoding="unicode")
    return {"geojson": geojson, "osm": xml, "nombre": len(depots), "nb_synthetiques_exclus": 0 if demo else len(synth)}
