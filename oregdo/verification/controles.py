"""Les contrôles de vérification : un contrôle = une fonction indépendante qui renvoie un `Resultat`.

Chaque résultat porte un motif en français, lisible par un non-informaticien.
Tous les seuils viennent de commune_config.yaml (section verification).
"""
from ..config import COMMUNE_DEFAUT
import math
from dataclasses import dataclass, asdict
from datetime import datetime, timezone
from functools import lru_cache
from io import BytesIO

from shapely import prepared
from shapely.geometry import Point
from shapely.ops import unary_union

# États possibles d'un contrôle. « neutre » = rien à reprocher mais rien à ajouter (ex. un seul enquêteur).
OK, PARTIEL, ECHEC, NON_APPLICABLE, NEUTRE = "ok", "partiel", "echec", "non_applicable", "neutre"
GRAVE, BLOQUANT = "grave", "bloquant"   # grave : ne peut pas être « vérifié » ; bloquant : « rejeté »

# Fractions de points accordées dans les cas intermédiaires. Surchargeables dans la config
# (verification.fractions.<nom>), ces valeurs ne sont que des défauts.
FRACTIONS_DEFAUT = {"secteur_absent": 0.8, "secteur_different": 0.4, "exif_date_ecart": 0.5, "exif_absent_partiel": 0.5}


@dataclass
class Resultat:
    controle: str
    etat: str
    fraction: float      # part des points du contrôle obtenue (0 à 1)
    motif: str
    gravite: str | None = None
    bonus: bool = False  # vrai pour la corroboration (ajoute le bonus de la config)

    def en_dict(self):
        return asdict(self)


def fraction_param(cfg, nom):
    surcharge = getattr(getattr(cfg.verification, "fractions", None), nom, None)
    return FRACTIONS_DEFAUT[nom] if surcharge is None else surcharge


def distance_m(lat1, lon1, lat2, lon2) -> float:
    """Distance (mètres) entre deux points GPS, formule de haversine."""
    if not all(isinstance(x, (int, float)) and math.isfinite(x) for x in (lat1, lon1, lat2, lon2)):
        return math.inf                      # valeur absurde : jamais « proche », jamais d'erreur
    p1, p2 = math.radians(lat1), math.radians(lat2)
    a = math.sin((p2 - p1) / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(math.radians(lon2 - lon1) / 2) ** 2
    return 6371008.8 * 2 * math.asin(math.sqrt(min(1.0, max(0.0, a))))


def lire_date(texte) -> datetime | None:
    """Date ISO 8601 -> datetime avec fuseau (heure sans fuseau = UTC, soit l'heure de Ouaga). None si illisible."""
    if texte is None or texte == "":
        return None
    try:
        d = texte if isinstance(texte, datetime) else datetime.fromisoformat(str(texte).strip().replace("Z", "+00:00"))
    except ValueError:
        return None
    return d if d.tzinfo else d.replace(tzinfo=timezone.utc)


# ---------------------------------------------------------------- couches de référence
class Reference:
    """Couches du pack (commune, secteurs, eau, aéroport) préparées pour des tests rapides."""

    def __init__(self, commune=COMMUNE_DEFAUT):
        from ..geo import couche
        self.commune = prepared.prep(unary_union([g.buffer(0) for g in couche("commune").geometry]))
        self.secteurs = [(str(r.id), str(r.nom), prepared.prep(r.geometry.buffer(0))) for r in couche("secteurs").itertuples()]
        self.eau = prepared.prep(unary_union([g.buffer(0) for g in couche("eau").geometry]))
        self.aeroport = prepared.prep(unary_union([g.buffer(0) for g in couche("aeroport").geometry]))
        # Pas de couche « bâtiments » dans le pack : le contrôle sur bâtiment est signalé comme non vérifié.

    def dans_commune(self, lat, lon):
        return self.commune.covers(Point(lon, lat))

    def secteur_de(self, lat, lon):
        p = Point(lon, lat)
        return next(((i, n) for i, n, g in self.secteurs if g.covers(p)), None)


@lru_cache(maxsize=2)
def reference(commune=COMMUNE_DEFAUT) -> Reference:
    return Reference(commune)


# ---------------------------------------------------------------- 1. position
def controle_position(sig, ref, cfg) -> Resultat:
    nom = "position"
    try:
        lat, lon = float(sig["lat"]), float(sig["lon"])
        if not (math.isfinite(lat) and math.isfinite(lon)):
            raise ValueError
    except (KeyError, TypeError, ValueError):
        return Resultat(nom, ECHEC, 0, "Position absente ou illisible.", BLOQUANT)
    if lat == 0 and lon == 0:
        return Resultat(nom, ECHEC, 0, "Position (0, 0) : c'est la valeur d'un GPS qui n'a pas trouvé de signal, pas un lieu réel.", BLOQUANT)
    in_range = abs(lat) <= 90 and abs(lon) <= 180
    if in_range and ref.dans_commune(lat, lon):
        pass
    elif abs(lon) <= 90 and abs(lat) <= 180 and ref.dans_commune(lon, lat):
        return Resultat(nom, ECHEC, 0, "Latitude et longitude semblent inversées : le point serait dans la commune une fois remis dans le bon sens.", BLOQUANT)
    else:
        return Resultat(nom, ECHEC, 0, "Le point est en dehors de la commune.", BLOQUANT)
    # Tant que le découpage en secteurs du pack est provisoire (synthétique), on ne reproche pas au déclarant un secteur
    # « qui ne correspond pas » : ce serait punir de vrais signalements pour une erreur de notre couche, pas la leur.
    if not getattr(cfg.verification, "secteurs_officiels", True):
        return Resultat(nom, OK, 1, "Dans la commune. Le découpage en secteurs de ce pack est provisoire : le secteur déclaré n'est pas contrôlé.")
    trouve = ref.secteur_de(lat, lon)
    declare = (str(sig.get("secteur") or "")).strip().lower()
    if not declare:
        return Resultat(nom, PARTIEL, fraction_param(cfg, "secteur_absent"), "Dans la commune ; secteur non déclaré.")
    if trouve and declare in (trouve[0].lower(), trouve[1].lower()):
        return Resultat(nom, OK, 1, f"Dans la commune et dans le secteur déclaré ({trouve[1]}).")
    ou = f"dans le secteur {trouve[1]}" if trouve else "dans aucun secteur connu"
    return Resultat(nom, PARTIEL, fraction_param(cfg, "secteur_different"), f"Dans la commune, mais le secteur déclaré ({sig['secteur']}) ne correspond pas : le point est {ou}.")


# ---------------------------------------------------------------- 2. lieu possible
def controle_lieu(sig, ref, cfg) -> Resultat:
    nom = "lieu_possible"
    try:
        p = Point(float(sig["lon"]), float(sig["lat"]))
    except (KeyError, TypeError, ValueError):
        return Resultat(nom, NON_APPLICABLE, 0, "Lieu non évalué : position inutilisable.")
    if ref.eau.covers(p):
        return Resultat(nom, ECHEC, 0, "Le point est dans un plan d'eau : on ne peut pas y déposer de déchets.", BLOQUANT)
    if ref.aeroport.covers(p):
        return Resultat(nom, ECHEC, 0, "Le point est dans l'emprise de l'aéroport (piste ou zone interdite).", BLOQUANT)
    return Resultat(nom, OK, 1, "Lieu plausible : ni eau, ni aéroport (couche des bâtiments non disponible dans le pack).")


# ---------------------------------------------------------------- 3. doublons
def _proches(sig, hist, rayon, seulement_actifs=True):
    try:
        lat, lon = float(sig["lat"]), float(sig["lon"])
    except (KeyError, TypeError, ValueError):
        return []
    marge = rayon / 111_000 * 1.5 + 1e-5       # préfiltre rapide avant le calcul exact
    return [h for h in hist if h.get("lat") is not None and h.get("lon") is not None
            and (not seulement_actifs or h["statut"] != "rejete")
            and abs(h["lat"] - lat) <= marge and distance_m(lat, lon, h["lat"], h["lon"]) <= rayon]


def _secondes(a, b):
    da, db = lire_date(a), lire_date(b)
    return None if da is None or db is None else abs((da - db).total_seconds())


def controle_doublons(sig, hist, cfg) -> Resultat:
    nom, v = "doublons", cfg.verification
    if sig.get("lat") is None or sig.get("lon") is None:
        return Resultat(nom, NON_APPLICABLE, 0, "Doublons non évalués : position inutilisable.")
    meme_appareil = [h for h in _proches(sig, hist, v.doublons.rayon_m, False)
                     if sig.get("appareil") and h.get("appareil") == sig["appareil"]]
    rapides = [h for h in meme_appareil
               if (s := _secondes(sig.get("horodatage"), h.get("horodatage"))) is not None and s <= v.rafale.fenetre_secondes]
    if rapides:
        return Resultat(nom, ECHEC, 0, f"Même appareil, même endroit, à quelques secondes d'intervalle (déjà {len(rapides)} fois) : tentative de gonflage, pas une confirmation.", BLOQUANT)
    voisins = _proches(sig, hist, v.doublons.rayon_m)
    memes = [h for h in voisins if sig.get("enqueteur") and h.get("enqueteur") == sig["enqueteur"]]
    if memes:
        return Resultat(nom, ECHEC, 0, f"Ce tas a déjà été signalé par le même enquêteur (signalement n° {memes[0]['id']}) : ce n'est pas une nouvelle confirmation.", GRAVE)
    if voisins:
        return Resultat(nom, OK, 1, f"Même tas que {len(voisins)} signalement(s) d'autres enquêteurs : il sera regroupé dans un seul dépotoir.")
    return Resultat(nom, OK, 1, "Premier signalement à cet endroit.")


# ---------------------------------------------------------------- 4. photo réutilisée / 5. EXIF
def _gps_decimal(valeurs, ref):
    deg = float(valeurs[0]) + float(valeurs[1]) / 60 + float(valeurs[2]) / 3600
    return -deg if ref in ("S", "W") else deg


def analyser_photo(octets) -> dict:
    """Lit une photo : empreinte perceptuelle (entier) et EXIF utile (position, date). Ne plante jamais."""
    import imagehash
    from PIL import Image
    try:
        img = Image.open(BytesIO(octets))
        img.load()
    except Exception:
        return {"erreur": "photo illisible ou format inconnu"}
    from .plausibilite import mesurer
    info = {"empreinte": int(str(imagehash.phash(img)), 16), "exif": None}
    try:
        info["mesures"] = mesurer(img)
    except Exception:
        info["mesures"] = {}
    try:
        exif = img.getexif()
        gps, details = exif.get_ifd(0x8825), exif.get_ifd(0x8769)
        e = {}
        if gps and 2 in gps and 4 in gps:
            e["lat"], e["lon"] = _gps_decimal(gps[2], gps.get(1)), _gps_decimal(gps[4], gps.get(3))
        brut = details.get(36867) or exif.get(306)
        if brut:
            e["date"] = datetime.strptime(str(brut), "%Y:%m:%d %H:%M:%S").replace(tzinfo=timezone.utc)
        info["exif"] = e or None
    except Exception:
        info["exif"] = None
    return info


def controle_photo(photos, connues, cfg) -> Resultat:
    """`photos` : liste de dicts de analyser_photo ; `connues` : [(id_signalement, empreinte)]."""
    nom, seuil = "photo_reutilisee", cfg.verification.photo.distance_hash_max
    if not photos:
        return Resultat(nom, NON_APPLICABLE, 0, "Pas de photo : contrôle impossible.")
    lisibles = [p for p in photos if "empreinte" in p]
    if not lisibles:
        return Resultat(nom, ECHEC, 0, "Photo illisible : impossible de la comparer.")
    for p in lisibles:
        for sid, emp in connues:
            d = (p["empreinte"] ^ emp).bit_count()
            if d <= seuil:
                return Resultat(nom, ECHEC, 0, f"Cette photo ressemble à celle du signalement n° {sid} (écart {d} sur 64) : photo probablement réutilisée.", GRAVE)
    return Resultat(nom, OK, 1, "Photo jamais vue auparavant.")


def controle_exif(photos, sig, cfg) -> Resultat:
    nom, v = "exif", cfg.verification.exif
    if not photos:
        return Resultat(nom, NON_APPLICABLE, 0, "Pas de photo : EXIF non vérifiable.")
    exifs = [p["exif"] for p in photos if p.get("exif")]
    if not exifs:
        return Resultat(nom, NON_APPLICABLE, 0, "Photo sans données EXIF (indice faible : beaucoup d'applications les retirent).")
    notes, motifs, grave = [], [], None
    for e in exifs:
        if "lat" in e and sig.get("lat") is not None:
            d = distance_m(e["lat"], e["lon"], float(sig["lat"]), float(sig["lon"]))
            ok = d <= v.ecart_position_max_m
            notes.append(1 if ok else 0)
            motifs.append("position de la photo cohérente" if ok else f"la photo a été prise à {d:.0f} m du point déclaré")
            grave = grave or (None if ok else GRAVE)
        ref_date = lire_date(sig.get("horodatage")) or lire_date(sig.get("recu_le"))
        if "date" in e and ref_date:
            h = abs((e["date"] - ref_date).total_seconds()) / 3600
            ok = h <= v.ecart_date_max_heures
            notes.append(1 if ok else fraction_param(cfg, "exif_date_ecart"))
            motifs.append("date de la photo cohérente" if ok else f"la photo date de {h:.0f} h d'écart avec la déclaration")
    if not notes:
        return Resultat(nom, NON_APPLICABLE, 0, "EXIF présent mais sans position ni date exploitable.")
    f = sum(notes) / len(notes)
    return Resultat(nom, OK if f == 1 else (PARTIEL if f > 0 else ECHEC), f, "EXIF : " + " ; ".join(motifs) + ".", grave)


# ---------------------------------------------------------------- 6. horodatage
def controle_horodatage(sig, hist, cfg, maintenant=None) -> Resultat:
    nom, v = "horodatage", cfg.verification
    if not sig.get("horodatage"):
        return Resultat(nom, NON_APPLICABLE, 0, "Pas de date déclarée.")
    d = lire_date(sig["horodatage"])
    if d is None:
        return Resultat(nom, ECHEC, 0, f"Date illisible : « {sig['horodatage']} ».", GRAVE)
    now = maintenant or datetime.now(timezone.utc)
    if (d - now).total_seconds() > v.horodatage.tolerance_futur_minutes * 60:
        return Resultat(nom, ECHEC, 0, "La date déclarée est dans le futur.", BLOQUANT)
    app = sig.get("appareil")
    fenetre = [h for h in hist if app and h.get("appareil") == app
               and (s := _secondes(sig["horodatage"], h.get("horodatage"))) is not None and s <= v.rafale.fenetre_secondes]
    if sig.get("lat") is not None:
        for h in fenetre:
            if h.get("lat") is None:
                continue
            km = distance_m(float(sig["lat"]), float(sig["lon"]), h["lat"], h["lon"]) / 1000
            heures = max(_secondes(sig["horodatage"], h["horodatage"]), 1) / 3600
            if km / heures > v.rafale.vitesse_max_kmh:
                return Resultat(nom, ECHEC, 0, f"Rafale impossible : le même appareil était à {km:.1f} km de là il y a {heures * 3600:.0f} secondes.", BLOQUANT)
    rz = v.rafale_zone
    if sig.get("lat") is not None:
        zone = {h.get("enqueteur") or h.get("appareil") for h in _proches(sig, hist, rz.rayon_m, False)
                if (s := _secondes(sig["horodatage"], h.get("horodatage"))) is not None and s <= rz.fenetre_secondes}
        zone.discard(None)
        if len(zone | {sig.get("enqueteur") or sig.get("appareil")}) >= rz.min_enqueteurs:
            return Resultat(nom, ECHEC, 0, f"Rafale coordonnée : {len(zone) + 1} enquêteurs différents ont signalé la même zone en moins de {rz.fenetre_secondes} s : ce n'est pas une confirmation indépendante.", GRAVE)
    if len(fenetre) >= v.rafale.max_signalements_identiques:
        return Resultat(nom, ECHEC, 0, f"Rafale : {len(fenetre)} signalements du même appareil en moins de {v.rafale.fenetre_secondes} s.", BLOQUANT)
    return Resultat(nom, OK, 1, "Date plausible, pas de rafale.")


# ---------------------------------------------------------------- 7. corroboration
def controle_corroboration(sig, hist, cfg, preuve_moi=False) -> Resultat:
    """Bonus seulement si les signalements viennent d'appareils ET d'enquêteurs distincts, et si au moins un
    porte une preuve (photo plausible ou EXIF cohérent). Sinon : pas de bonus (et le plafond « sans photo » reste)."""
    nom, v = "corroboration", cfg.verification
    moi = sig.get("enqueteur") or sig.get("appareil")
    voisins = [h for h in _proches(sig, hist, v.doublons.rayon_m)
               if (h.get("enqueteur") or h.get("appareil")) and (h.get("enqueteur") or h.get("appareil")) != moi
               and not (sig.get("appareil") and h.get("appareil") == sig["appareil"])
               and not (sig.get("enqueteur") and h.get("enqueteur") == sig["enqueteur"])]
    autres = {h.get("enqueteur") or h.get("appareil") for h in voisins}
    n = len(autres) + (1 if moi else 0)
    if not (moi and n >= v.corroboration.enqueteurs_min):
        return Resultat(nom, NEUTRE, 0, "Un seul enquêteur pour l'instant : pas de confirmation indépendante.")
    if preuve_moi or any(h.get("photo_plausible") or h.get("exif_coherent") for h in voisins):
        return Resultat(nom, OK, 1, f"Confirmé par {n} enquêteurs et appareils différents, preuve photo ou EXIF à l'appui : bonus de confiance.", None, True)
    return Resultat(nom, NEUTRE, 0, f"{n} enquêteurs différents mais aucune photo plausible ni EXIF cohérent : pas de bonus (confirmation sur place nécessaire).")


# ---------------------------------------------------------------- 8. classifieur d'image (optionnel)
CLASSIFIEUR = None  # à brancher : fonction(octets) -> probabilité 0..1 que la photo montre un dépotoir


def controle_classifieur(octets_photos, cfg) -> Resultat | None:
    """None si le drapeau est coupé (cas par défaut). Sans modèle branché : non applicable."""
    if not cfg.verification.classifieur_image.actif:
        return None
    nom = "classifieur_image"
    if not octets_photos or CLASSIFIEUR is None:
        return Resultat(nom, NON_APPLICABLE, 0, "Classifieur actif mais sans photo ou sans modèle installé.")
    p = max(CLASSIFIEUR(o) for o in octets_photos)
    return Resultat(nom, OK if p >= 0.5 else ECHEC, p, f"Le classifieur voit un dépotoir avec {p:.0%} de certitude.")
