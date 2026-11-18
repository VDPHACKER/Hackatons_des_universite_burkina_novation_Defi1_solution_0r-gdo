"""Collecte de terrain SIMULÉE dans un secteur (le jury a demandé de simuler la collecte réelle).

L'équipe (3 membres) parcourt un secteur pendant deux matinées avec l'application et signale les tas qu'elle voit.
Comme la VÉRITÉ TERRAIN est connue (où sont vraiment les tas), on mesure ce que le pipeline en fait : tas détectés,
signalements d'un même tas fusionnés en un seul dépotoir, faux dépotoirs créés par une mauvaise position GPS, erreur de position.

Ce qui est simulé, et pourquoi :
- les tas sont au bord des voies du secteur (là où les dépôts sauvages se forment) ;
- chaque membre parcourt sa zone à pied (4 km/h, environ 4 minutes par signalement), à partir de 8 h ;
- il voit un tas de sa zone 8 fois sur 10 ; un second membre repasse sur 40 % des tas le lendemain (confirmation) ;
- le GPS d'un téléphone : précision médiane ~9 m, et 4 % de mauvais relevés (80 à 250 m d'erreur, en ville dense) ;
- 90 % des signalements ont une photo (dont la position EXIF est celle du téléphone) ; 3 % sont envoyés deux fois par erreur.

Tout est marqué synthétique. Commande :
    python -m oregdo.verification.collecte_simulee                  (secteur le plus peuplé ; bilan sans toucher à la base)
    python -m oregdo.verification.collecte_simulee --secteur S12 --charger   (ajoute aussi la collecte à la base de l'application)
Sorties dans livrables/collecte_simulee/ : export au format KoboToolbox (CSV), GeoJSON (licence ODbL), vérité terrain, bilan.md.
"""
import argparse
import csv
import io
import json
import math
import random
import tempfile
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path

from shapely.geometry import Point

from ..config import RACINE, charger_config
from ..geo import couche
from . import base, controles, doublons, score
from .synthetique import exif_fictif, photo_synthetique

GRAINE = 20261118
EQUIPE = ("BN-1", "BN-2", "BN-3")         # les 3 membres de l'équipe Burkina_Novation (identifiants de collecte anonymes)
SORTIE = RACINE / "livrables" / "collecte_simulee"
M_LAT = 111_320.0


def _decaler(lat, lon, est_m, nord_m):
    return lat + nord_m / M_LAT, lon + est_m / (M_LAT * math.cos(math.radians(lat)))


def _distance_m(a, b):
    dy = (a[0] - b[0]) * M_LAT
    dx = (a[1] - b[1]) * M_LAT * math.cos(math.radians(a[0]))
    return math.hypot(dx, dy)


def choisir_secteur(code=None):
    s = couche("secteurs")
    if code:
        ligne = s[(s["id"] == code) | (s["nom"] == code)]
        if ligne.empty:
            raise SystemExit(f"Secteur inconnu « {code} » : choisir parmi {', '.join(s['id'])}.")
        return ligne.iloc[0]
    return s.sort_values("population", ascending=False).iloc[0]


def tas_verite(rng, secteur, ref, n):
    """Positions vraies des tas : au bord d'une voie du secteur (4 à 15 m de l'axe), tirées selon la longueur des voies."""
    poly = secteur.geometry
    lignes = []
    for g in couche("routes").geometry:
        if g is None or not g.intersects(poly):
            continue
        m = g.intersection(poly)
        for l in getattr(m, "geoms", [m]):
            if l.geom_type == "LineString" and l.length > 0:
                lignes.append(l)
    if not lignes:
        raise SystemExit("Aucune voie dans ce secteur : impossible de placer les tas.")
    poids = [l.length for l in lignes]
    tas, essais = [], 0
    while len(tas) < n and essais < n * 200:
        essais += 1
        p = rng.choices(lignes, weights=poids)[0].interpolate(rng.random(), normalized=True)
        d, ang = rng.uniform(4, 15), rng.uniform(0, 2 * math.pi)
        lat, lon = _decaler(p.y, p.x, d * math.cos(ang), d * math.sin(ang))
        if not poly.covers(Point(lon, lat)) or ref.eau.covers(Point(lon, lat)):
            continue
        if any(_distance_m((lat, lon), (t["lat"], t["lon"])) < 60 for t in tas):     # deux tas distincts : au moins 60 m
            continue
        tas.append({"id": f"T{len(tas) + 1:02d}", "lat": lat, "lon": lon,
                    "taille": rng.choices(["petit", "moyen", "grand", "tres_grand"], [40, 35, 20, 5])[0],
                    "nature": rng.choice(["ordures menagères", "plastiques", "mixte", "gravats", "végétaux"]),
                    "caniveau": rng.random() < 0.3})
    return tas


def _zone(t, centre):
    """Zone d'un membre : un tiers du secteur, découpé en trois secteurs angulaires autour de son centre."""
    angle = math.degrees(math.atan2(t["lat"] - centre.y, t["lon"] - centre.x)) % 360
    return int(angle // 120)


def _gps(rng, lat, lon):
    """Position et précision annoncées par un téléphone, à partir de la vraie position."""
    if rng.random() < 0.04:                                         # mauvais relevé : réflexions sur les murs, ciel masqué
        err, prec = rng.uniform(80, 250), rng.uniform(60, 200)
    else:
        prec = min(30.0, max(4.0, rng.lognormvariate(math.log(9), 0.45)))
        err = abs(rng.gauss(0, prec / 1.6))
    a = rng.uniform(0, 2 * math.pi)
    la, lo = _decaler(lat, lon, err * math.cos(a), err * math.sin(a))
    return la, lo, prec, err


def simuler(graine=GRAINE, secteur=None, n_tas=30, maintenant=None):
    """Renvoie (secteur, vérité terrain, signalements). Chaque signalement : sig (comme l'application), photos, tas vrai, erreur GPS."""
    rng = random.Random(graine)
    ref = controles.reference()
    sec = choisir_secteur(secteur)
    tas = tas_verite(rng, sec, ref, n_tas)
    centre = sec.geometry.centroid
    maintenant = maintenant or datetime.now(timezone.utc).replace(microsecond=0)
    jour1 = (maintenant - timedelta(days=2)).replace(hour=8, minute=0, second=0)    # 8 h à Ouagadougou = 8 h UTC
    sorties = []
    passages = {m: [] for m in EQUIPE}
    for t in tas:
        principal = EQUIPE[_zone(t, centre)]
        if rng.random() < 0.8:
            passages[principal].append((1, t))
        if rng.random() < 0.4:                                        # un autre membre repasse le lendemain
            passages[rng.choice([m for m in EQUIPE if m != principal])].append((2, t))
    for membre, liste in passages.items():
        appareil = "TEL-" + membre
        for jour in (1, 2):
            a_faire = [t for j, t in liste if j == jour]
            pos, heure = (centre.y, centre.x), jour1 + timedelta(days=jour - 1, minutes=rng.uniform(0, 20))
            while a_faire:                                           # parcours : toujours le tas le plus proche
                t = min(a_faire, key=lambda x: _distance_m(pos, (x["lat"], x["lon"])))
                a_faire.remove(t)
                heure += timedelta(minutes=_distance_m(pos, (t["lat"], t["lon"])) / 66.7 + rng.uniform(3, 5))   # 4 km/h + saisie
                pos = (t["lat"], t["lon"])
                la, lo, prec, err = _gps(rng, *pos)
                photos = [photo_synthetique(rng.randrange(10**9), exif=exif_fictif(la, lo, heure))] if rng.random() < 0.9 else []
                sig = {"lat": la, "lon": lo, "precision_m": round(prec, 1), "secteur": sec["nom"], "enqueteur": membre, "appareil": appareil,
                       "horodatage": heure.isoformat(), "taille": t["taille"], "nature": t["nature"], "caniveau": t["caniveau"],
                       "accessibilite": "camion" if t["taille"] in ("grand", "tres_grand") else "tricycle"}
                sorties.append({"sig": sig, "photos": photos, "tas": t["id"], "erreur_m": round(err, 1)})
                if rng.random() < 0.03:                              # envoyé deux fois par erreur (réseau lent)
                    sig2 = {**sig, "horodatage": (heure + timedelta(seconds=rng.randint(20, 90))).isoformat()}
                    sorties.append({"sig": sig2, "photos": photos, "tas": t["id"], "erreur_m": round(err, 1), "renvoi": True})
    sorties.sort(key=lambda s: s["sig"]["horodatage"])
    return sec, tas, sorties


def evaluer(conn, tas, sorties, cfg, ref):
    """Passe chaque signalement dans le vrai pipeline, consolide les dépotoirs et compare à la vérité terrain."""
    statuts = {}
    for s in sorties:
        r = score.verifier_et_enregistrer(conn, s["sig"], s["photos"], ref, cfg, synthetique=True)
        statuts[r["statut"]] = statuts.get(r["statut"], 0) + 1
        s["statut"] = r["statut"]
    doublons.consolider(conn, cfg)
    deps = [dict(r) for r in conn.execute("SELECT id, lat, lon, nb_signalements, nb_enqueteurs, confiance FROM depotoir WHERE statut='verifie'")]
    pairs, faux = {}, []                    # un dépotoir correspond au tas vrai le plus proche s'il est à moins de 40 m
    for d in deps:
        t = min(tas, key=lambda x: _distance_m((d["lat"], d["lon"]), (x["lat"], x["lon"])))
        dist = _distance_m((d["lat"], d["lon"]), (t["lat"], t["lon"]))
        if dist <= 40:
            pairs.setdefault(t["id"], []).append(dist)
        else:
            faux.append(dist)
    signales = {s["tas"] for s in sorties}
    multi = [t for t in signales if len({s["sig"]["enqueteur"] for s in sorties if s["tas"] == t}) >= 2]
    distances = [d for v in pairs.values() for d in v]
    erreurs = sorted(s["erreur_m"] for s in sorties)
    return {
        "tas_vrais": len(tas), "tas_signales": len(signales), "signalements": len(sorties),
        "renvois": sum(1 for s in sorties if s.get("renvoi")), "sans_photo": sum(1 for s in sorties if not s["photos"]),
        "mauvais_gps": sum(1 for s in sorties if s["erreur_m"] > 60), "par_statut": statuts,
        "depotoirs": len(deps), "tas_retrouves": len(pairs),
        "tas_vus_par_deux_membres": len(multi), "fusionnes_en_un": sum(1 for t in multi if len(pairs.get(t, [])) == 1),
        "faux_depotoirs": len(faux), "erreur_position_m": round(sum(distances) / max(1, len(distances)), 1),
        "erreur_gps_mediane_m": erreurs[len(erreurs) // 2] if erreurs else None,
    }


def ecrire_sorties(sec, tas, sorties, bilan, dossier=SORTIE):
    """Export au format KoboToolbox (CSV), GeoJSON ouvert, vérité terrain et bilan lisible."""
    dossier.mkdir(parents=True, exist_ok=True)
    code = str(sec["id"])
    tampon = io.StringIO()
    w = csv.writer(tampon, lineterminator="\n")
    w.writerow(["start", "end", "today", "username", "deviceid", "geopoint", "taille", "nature", "caniveau", "photo", "secteur",
                "_id", "_uuid", "_submission_time", "synthetique"])
    for i, s in enumerate(sorties, 1):
        g, h = s["sig"], datetime.fromisoformat(s["sig"]["horodatage"])
        w.writerow([(h - timedelta(minutes=2)).isoformat(), h.isoformat(), h.date().isoformat(), g["enqueteur"], g["appareil"],
                    f"{g['lat']:.6f} {g['lon']:.6f} 305 {g['precision_m']}", g["taille"], g["nature"], "oui" if g["caniveau"] else "non",
                    f"photo_{i:03d}.jpg" if s["photos"] else "", g["secteur"], 1000 + i, str(uuid.UUID(int=random.Random(i).getrandbits(128))),
                    (h + timedelta(minutes=5)).isoformat(), "oui"])
    (dossier / f"collecte_{code}_kobo.csv").write_text(tampon.getvalue(), encoding="utf-8")
    geo = {"type": "FeatureCollection", "licence": "ODbL 1.0", "synthetique": True,
           "description": f"Collecte de terrain SIMULÉE (Orẽgdo, équipe Burkina_Novation), {sec['nom']} de Ouagadougou : données fictives.",
           "features": [{"type": "Feature", "geometry": {"type": "Point", "coordinates": [round(s["sig"]["lon"], 6), round(s["sig"]["lat"], 6)]},
                         "properties": {k: s["sig"][k] for k in ("horodatage", "enqueteur", "taille", "nature", "caniveau", "precision_m", "secteur")}
                         | {"statut": s.get("statut"), "photo": bool(s["photos"]), "synthetique": True}} for s in sorties]}
    (dossier / f"collecte_{code}.geojson").write_text(json.dumps(geo, ensure_ascii=False, indent=1), encoding="utf-8")
    verite = {"type": "FeatureCollection", "synthetique": True, "features": [
        {"type": "Feature", "geometry": {"type": "Point", "coordinates": [round(t["lon"], 6), round(t["lat"], 6)]},
         "properties": {k: t[k] for k in ("id", "taille", "nature", "caniveau")}} for t in tas]}
    (dossier / f"verite_terrain_{code}.geojson").write_text(json.dumps(verite, ensure_ascii=False, indent=1), encoding="utf-8")
    b = bilan

    def pc(a, n):
        return f"{100 * a / n:.0f} %" if n else "–"
    texte = f"""# Collecte de terrain simulée : {sec['nom']} (Ouagadougou)

**Données fictives.** Le jury a demandé de simuler la collecte réelle : ce fichier décrit une campagne simulée de l'équipe
Burkina_Novation et ce que la chaîne de vérification d'Orẽgdo en a fait, comparé à la vérité terrain (connue ici).
Reproductible : `python -m oregdo.verification.collecte_simulee --secteur {code}` (graine fixe).

## Protocole simulé
- Secteur : **{sec['nom']}** ({int(sec['population']):,} habitants selon le pack, arrondissement {sec.get('arrondissement', '?')}).
- **{b['tas_vrais']} tas réels** placés au bord des voies du secteur (4 à 15 m de l'axe, au moins 60 m entre deux tas).
- **3 membres** (BN-1 à BN-3), chacun dans un tiers du secteur, deux matinées, à pied (4 km/h).
- Un membre voit 8 tas sur 10 de sa zone ; un second membre repasse sur 4 tas sur 10 le lendemain.
- GPS de téléphone : précision médiane ~9 m, 4 % de mauvais relevés (80 à 250 m). 90 % des signalements avec photo. 3 % envoyés deux fois.

## Résultats
| Mesure | Valeur |
|---|---|
| Signalements envoyés | {b['signalements']} (dont {b['renvois']} renvoi(s) par erreur, {b['sans_photo']} sans photo, {b['mauvais_gps']} avec un mauvais GPS) |
| Statuts après contrôle | {', '.join(f'{k} : {v}' for k, v in sorted(b['par_statut'].items()))} |
| Tas réels signalés au moins une fois | {b['tas_signales']} sur {b['tas_vrais']} ({pc(b['tas_signales'], b['tas_vrais'])}) |
| Tas réels retrouvés comme dépotoir vérifié | {b['tas_retrouves']} sur {b['tas_signales']} signalés ({pc(b['tas_retrouves'], b['tas_signales'])}) |
| Tas vus par deux membres, fusionnés en un seul dépotoir | {b['fusionnes_en_un']} sur {b['tas_vus_par_deux_membres']} |
| Faux dépotoirs (à plus de 40 m de tout tas réel) | {b['faux_depotoirs']} |
| Erreur de position d'un dépotoir (moyenne) | {b['erreur_position_m']} m (erreur GPS médiane des signalements : {b['erreur_gps_mediane_m']} m) |

## Lecture
- Un tas que personne n'a vu ne peut pas être retrouvé : la couverture dépend du passage des équipes, pas du logiciel.
- Un signalement sans photo et non confirmé reste « à confirmer » : il attend la visite d'un agent, il n'entre pas dans le plan.
- Les renvois par erreur d'un même téléphone ne valent pas confirmation et ne créent pas de second dépotoir.
- Ce que la simulation a appris : un mauvais relevé GPS (80 à 250 m) créait un faux dépotoir, car la photo et ses EXIF portent la
  même erreur. Depuis, une précision annoncée au-delà de `precision_gps_max_m` (50 m, fichier de paramètres) plafonne le signalement
  à « à confirmer » : il ne crée plus de dépotoir tant qu'un agent n'a pas confirmé le lieu.

## Fichiers
- `collecte_{code}_kobo.csv` : la collecte au format d'un export KoboToolbox (s'importe tel quel dans Orẽgdo, écran « Importer une collecte » ;
  sans les photos, les lignes y restent « à confirmer »).
- `collecte_{code}.geojson` : les signalements et leur statut, licence ODbL (fictifs).
- `verite_terrain_{code}.geojson` : position réelle des tas (ce que la simulation sait et que l'application ignore).
"""
    (dossier / "bilan.md").write_text(texte, encoding="utf-8")
    (dossier / "bilan.json").write_text(json.dumps(bilan, ensure_ascii=False, indent=1), encoding="utf-8")   # pour les graphiques du rapport
    return dossier


def main(argv=None):
    p = argparse.ArgumentParser(description="Collecte de terrain simulée dans un secteur, évaluée contre la vérité terrain.")
    p.add_argument("--secteur", help="identifiant (S12) ou nom du secteur ; par défaut le plus peuplé")
    p.add_argument("--tas", type=int, default=30, help="nombre de tas réels dans le secteur (défaut 30)")
    p.add_argument("--graine", type=int, default=GRAINE)
    p.add_argument("--charger", action="store_true", help="ajoute aussi la collecte (marquée synthétique) à la base de l'application")
    a = p.parse_args(argv)
    cfg, ref = charger_config(), controles.reference()
    sec, tas, sorties = simuler(a.graine, a.secteur, a.tas)
    with tempfile.TemporaryDirectory() as d:                  # évaluation sur une base vide : seule cette campagne compte
        conn = base.ouvrir(Path(d) / "evaluation.db")
        try:
            bilan = evaluer(conn, tas, sorties, cfg, ref)
        finally:
            conn.close()
    dossier = ecrire_sorties(sec, tas, sorties, bilan)
    print(json.dumps(bilan, ensure_ascii=False, indent=2))
    print(f"Fichiers écrits dans {dossier}")
    if a.charger:
        conn = base.ouvrir()
        try:
            for s in sorties:
                score.verifier_et_enregistrer(conn, s["sig"], s["photos"], ref, cfg, synthetique=True)
            doublons.consolider(conn, cfg)
            print("Collecte ajoutée à la base de l'application (marquée synthétique).")
        finally:
            conn.close()


if __name__ == "__main__":
    main()
