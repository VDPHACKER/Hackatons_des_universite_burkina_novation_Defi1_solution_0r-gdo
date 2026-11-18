"""Import d'un fichier brut (CSV ou GeoJSON), souvent sans photo, dans le même pipeline que l'application.

Un fichier mal formé ne fait jamais planter le programme : chaque ligne illisible est refusée avec une
explication (et conservée dans la table ligne_refusee), les autres lignes sont traitées normalement.
Une ligne lisible mais absurde (hors commune, dans l'eau, (0,0)...) n'est PAS refusée ici : elle est
enregistrée puis rejetée par les contrôles, avec ses motifs.
"""
import csv
import io
import json
import math
import re

from . import base, score

ALIAS = {
    "lat": ("lat", "latitude", "y"), "lon": ("lon", "lng", "long", "longitude", "x"),
    "secteur": ("secteur", "sector"), "taille": ("taille", "taille_estimee", "volume"),
    "nature": ("nature", "type_dechets", "dechets"), "caniveau": ("caniveau", "caniveau_bouche"),
    "accessibilite": ("accessibilite", "acces"), "enqueteur": ("enqueteur", "enqueteur_id", "agent"),
    "appareil": ("appareil", "appareil_id", "device", "deviceid", "device_id", "imei"),
    "horodatage": ("horodatage", "date", "datetime", "date_heure", "_submission_time", "end", "start", "today"),
}
# Exports ODK / KoboToolbox (outils de collecte hors ligne très utilisés par les ONG et les services techniques) : la position est
# dans UNE colonne, « lat lon altitude précision » (geopoint) ou « [lat, lon] » (_geolocation), parfois préfixée par un groupe
# de formulaire (« groupe/geopoint »). Les identifiants de colonne « enqueteur » y portent d'autres noms.
POSITION_ODK = ("geopoint", "_geolocation", "geolocation", "gps", "position", "localisation", "location")
ALIAS["enqueteur"] = ALIAS["enqueteur"] + ("username", "_submitted_by")
ALIAS["precision_m"] = ("precision_m", "precision", "accuracy", "precision_gps", "gps_accuracy", "_geopoint_precision")
# Exports SIG (QGIS, PostGIS, ogr2ogr) : la position est une géométrie en texte WKT (« POINT (lon lat) », parfois un polygone).
COLONNES_WKT = ("wkt", "geometry", "geom", "the_geom", "geometrie", "géométrie")
SEPARATEURS = (",", ";", "\t", "|")
_NOMBRE = re.compile(r"-?\d+(?:\.\d+)?(?:[eE][-+]?\d+)?")


def _point_wkt(minus: dict):
    """(lat, lon) lus dans une colonne WKT, ou None. Un polygone ou une ligne (tas cartographié comme une surface) donne un point
    situé à l'intérieur de la forme. Lève ValueError si le texte WKT est illisible."""
    from shapely import wkt
    for cle in COLONNES_WKT:
        val = minus.get(cle)
        if val is not None and str(val).strip():
            try:
                g = wkt.loads(str(val).strip())
            except Exception as e:                      # shapely lève des erreurs variées selon la version
                raise ValueError(f"géométrie WKT illisible ({str(val)[:40]!r})") from e
            if g.is_empty:
                raise ValueError("géométrie WKT vide")
            p = g if g.geom_type == "Point" else g.representative_point()
            return p.y, p.x
    return None


def _position_odk(minus: dict):
    """(lat, lon) lus dans une colonne ODK/Kobo, ou None. Latitude d'abord, comme dans geopoint et _geolocation."""
    for cle, val in minus.items():
        if cle.rsplit("/", 1)[-1] in POSITION_ODK and val is not None:
            texte = str(val)
            # « 12.3, -1.5 » : la virgule sépare ; « 12,3 -1,5 » (sans point) : la virgule est décimale.
            texte = texte.replace(",", " ") if "." in texte else texte.replace(",", ".")
            nombres = _NOMBRE.findall(texte)
            if len(nombres) >= 2:
                return nombres[0], nombres[1]
    return None


def _nombre(valeur):
    """Convertit '12,35' ou 12.35 en float. Lève ValueError si impossible ou non fini."""
    if isinstance(valeur, bool) or valeur is None or str(valeur).strip() == "":
        raise ValueError("valeur vide")
    x = float(str(valeur).strip().replace(",", ".")) if not isinstance(valeur, (int, float)) else float(valeur)
    if not math.isfinite(x):
        raise ValueError("valeur non finie")
    return x


def _booleen(v):
    if v is None or str(v).strip() == "":
        return None
    return str(v).strip().lower() in ("1", "oui", "o", "true", "vrai", "yes", "y")


def _normaliser(brut: dict, source: str):
    """Dictionnaire brut -> signalement standard. Lève ValueError (message lisible) si lat/lon inutilisables."""
    minus = {str(k).strip().lower(): v for k, v in brut.items() if k is not None}
    for k in list(minus):                      # « groupe/champ » (ODK, Kobo) : le nom court sert aussi
        minus.setdefault(k.rsplit("/", 1)[-1], minus[k])
    sig = {"source": source}
    for cible, noms in ALIAS.items():
        sig[cible] = next((minus[n] for n in noms if n in minus and str(minus[n]).strip() != ""), None)
    if sig["lat"] is None and sig["lon"] is None:
        position = _position_odk(minus) or _point_wkt(minus)
        if position:
            sig["lat"], sig["lon"] = position
    try:
        sig["lat"] = _nombre(sig["lat"])
    except (ValueError, TypeError):
        raise ValueError(f"latitude absente ou illisible ({brut.get('lat', brut.get('latitude'))!r})")
    try:
        sig["lon"] = _nombre(sig["lon"])
    except (ValueError, TypeError):
        raise ValueError(f"longitude absente ou illisible ({brut.get('lon', brut.get('longitude'))!r})")
    sig["caniveau"] = _booleen(sig["caniveau"])
    if sig["precision_m"] is None:                        # geopoint ODK/Kobo : « lat lon altitude précision »
        for cle, val in minus.items():
            if cle.rsplit("/", 1)[-1] == "geopoint" and val is not None:
                nombres = _NOMBRE.findall(str(val))
                if len(nombres) >= 4:
                    sig["precision_m"] = nombres[3]
    try:
        sig["precision_m"] = None if sig["precision_m"] is None else _nombre(sig["precision_m"])
    except (ValueError, TypeError):
        sig["precision_m"] = None                         # précision illisible : ignorée (elle n'est pas obligatoire)
    for k in ("secteur", "taille", "nature", "accessibilite", "enqueteur", "appareil", "horodatage"):
        sig[k] = None if sig[k] is None else str(sig[k]).strip()
    return sig


def _decoder(contenu: bytes) -> str:
    for enc in ("utf-8-sig", "cp1252"):
        try:
            return contenu.decode(enc)
        except UnicodeDecodeError:
            continue
    return contenu.decode("latin-1", errors="replace")


def lire_csv(texte):
    """Renvoie (lignes lisibles [(n°, dict)], lignes refusées [(n°, raison, contenu)], erreur_fichier)."""
    ok, refus = [], []
    premiere = texte.splitlines()[0] if texte.strip() else ""
    if not premiere:
        return ok, refus, "Le fichier CSV est vide."
    delim = max(SEPARATEURS, key=premiere.count)            # le séparateur le plus fréquent dans l'en-tête (virgule par défaut)
    if premiere.count(delim) == 0:
        delim = ","
    try:
        lecteur = csv.reader(io.StringIO(texte), delimiter=delim)
        entete = [h.strip().lower() for h in next(lecteur)]
        court = [h.rsplit("/", 1)[-1] for h in entete]
        a_lat_lon = any(n in court for n in ALIAS["lat"]) and any(n in court for n in ALIAS["lon"])
        if not a_lat_lon and not any(h in POSITION_ODK or h in COLONNES_WKT for h in court):
            return ok, refus, ("Colonnes de position introuvables : il faut « lat » et « lon » dans la première ligne "
                               "(ou une colonne « geopoint » / « _geolocation » d'ODK/Kobo, ou une géométrie « WKT » d'un logiciel SIG).")
        for ligne in lecteur:
            n = lecteur.line_num
            if not ligne or not any(c.strip() for c in ligne):
                continue
            if len(ligne) != len(entete):
                refus.append((n, f"{len(ligne)} colonnes au lieu de {len(entete)} attendues.", delim.join(ligne)))
                continue
            ok.append((n, dict(zip(entete, ligne))))
    except (csv.Error, StopIteration) as e:
        refus.append((0, f"Fichier CSV illisible à partir d'ici : {e}", ""))
    return ok, refus, None


def lire_geojson(texte):
    ok, refus = [], []
    try:
        data = json.loads(texte)
    except ValueError as e:
        return ok, refus, f"GeoJSON invalide (JSON mal formé) : {e}"
    # Un FeatureCollection, mais aussi une Feature seule ou une géométrie seule (exports de logiciels variés).
    if isinstance(data, dict) and data.get("type") == "Feature":
        data = {"type": "FeatureCollection", "features": [data]}
    elif isinstance(data, dict) and data.get("type") in GEOMETRIES:
        data = {"type": "FeatureCollection", "features": [{"type": "Feature", "geometry": data, "properties": {}}]}
    feats = data.get("features") if isinstance(data, dict) else None
    if not isinstance(feats, list):
        return ok, refus, "GeoJSON sans liste « features » : un FeatureCollection (ou une Feature) est attendu."
    for i, f in enumerate(feats, 1):
        try:
            for proprietes in _points_geojson(f):
                ok.append((i, proprietes))
        except (AttributeError, ValueError, TypeError) as e:
            refus.append((i, f"Élément {i} refusé : {e}.", json.dumps(f, ensure_ascii=False, default=str)[:300]))
    return ok, refus, None


GEOMETRIES = ("Point", "MultiPoint", "Polygon", "MultiPolygon", "LineString", "MultiLineString")


def _points_geojson(f: dict) -> list:
    """Propriétés + position pour chaque point d'une Feature : un Point donne un signalement, un MultiPoint un par point,
    une surface ou une ligne (tas cartographié comme une zone) un point situé à l'intérieur de la forme."""
    geom = f.get("geometry") or {}
    t, coords = geom.get("type"), geom.get("coordinates")
    props = dict(f.get("properties") or {})
    if t == "Point":
        points = [coords]
    elif t == "MultiPoint":
        points = coords if isinstance(coords, list) else []
    elif t in GEOMETRIES:
        from shapely.geometry import shape
        try:                                                # tout passe dans le try : une forme dégénérée donne un point vide
            p = shape(geom).representative_point()
            if p.is_empty:
                raise ValueError("forme vide")
            points, props["geometrie_source"] = [[p.x, p.y]], t
        except Exception as e:                              # erreurs de la bibliothèque géométrique : refus lisible, jamais de plantage
            raise ValueError(f"géométrie « {t} » illisible ou vide") from e
    else:
        raise ValueError(f"géométrie « {t} » non prise en charge : point, multipoint, ligne ou surface attendus")
    sortie = []
    for c in points:
        if not isinstance(c, list) or len(c) < 2:
            raise ValueError("coordonnées [longitude, latitude] attendues")
        sortie.append({**props, "lon": c[0], "lat": c[1]})
    if not sortie:
        raise ValueError("aucun point dans la géométrie")
    return sortie


class LimiteDepassee(ValueError):
    """Fichier trop gros ou trop long (message en français, prêt à afficher)."""


def verifier_limites(contenu: bytes, cfg):
    lim = cfg.verification.limites
    if len(contenu) > lim.fichier_octets_max:
        raise LimiteDepassee(f"Fichier trop volumineux ({len(contenu) // 1000} Ko) : la limite est de {lim.fichier_octets_max // 1000} Ko.")
    if contenu.count(bytes([10])) + 1 > lim.lignes_max + 1 and not contenu.lstrip().startswith(b"{"):
        raise LimiteDepassee(f"Trop de lignes : la limite est de {lim.lignes_max} lignes par fichier ; découpez le fichier.")


def importer(conn, nom_fichier, contenu: bytes, cfg, ref=None, synthetique=False, utilisateur=None, secteur_defaut=None) -> dict:
    """Importe un fichier CSV ou GeoJSON. Renvoie le détail des lignes acceptées et refusées.
    Les écritures sont groupées en UNE transaction ; historique et couches ne sont chargés qu'une fois."""
    verifier_limites(contenu or b"", cfg)
    texte = _decoder(contenu or b"")
    est_geojson = (nom_fichier or "").lower().endswith(("json", "geojson")) or texte.lstrip().startswith("{")
    source = "geojson" if est_geojson else "csv"
    lignes, refus, erreur = (lire_geojson if est_geojson else lire_csv)(texte)
    if len(lignes) > cfg.verification.limites.lignes_max:
        raise LimiteDepassee(f"Trop de lignes ({len(lignes)}) : la limite est de {cfg.verification.limites.lignes_max} par fichier ; découpez le fichier.")
    acceptees = []
    ref = ref or score.c.reference()
    ctx = score.Contexte(conn)
    for n, brut in lignes:
        try:
            sig = _normaliser(brut, source)
            if utilisateur:                      # import lié au compte de l'enquêteur et à son secteur
                sig["enqueteur"], sig["utilisateur"] = utilisateur, utilisateur
                sig["secteur"] = sig["secteur"] or secteur_defaut
        except ValueError as e:
            refus.append((n, f"Ligne {n} refusée : {e}.", str(brut)[:300]))
            continue
        try:
            r = score.verifier_et_enregistrer(conn, sig, (), ref, cfg, synthetique=synthetique, contexte=ctx, commit=False, utilisateur=utilisateur)
        except Exception as e:  # une ligne qui échoue ne doit pas arrêter les suivantes
            refus.append((n, f"Ligne {n} refusée : erreur inattendue ({type(e).__name__}).", str(brut)[:300]))
            continue
        acceptees.append({"ligne": n, "id": r["id"], "score": r["score"], "statut": r["statut"]})
    for n, raison, contenu_ligne in refus:
        conn.execute("INSERT INTO ligne_refusee (fichier, ligne, raison, contenu, date) VALUES (?,?,?,?,?)",
                     (nom_fichier, n, raison, contenu_ligne, base.maintenant()))
    conn.commit()
    return {"fichier": nom_fichier, "format": source, "erreur_fichier": erreur,
            "nb_acceptees": len(acceptees), "nb_refusees": len(refus) + (1 if erreur else 0),
            "acceptees": acceptees,
            "refusees": ([{"ligne": 0, "raison": erreur}] if erreur else []) +
                        [{"ligne": n, "raison": r} for n, r, _ in refus]}
