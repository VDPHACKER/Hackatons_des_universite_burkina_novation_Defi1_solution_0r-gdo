"""Jeu de données SYNTHÉTIQUE piégé, reproductible (graine fixe), pour tester et démontrer la vérification.

Tout ce qui est produit ici est fictif et étiqueté `synthetique=1` en base.
Commande : .venv\\Scripts\\python.exe -m oregdo.verification.synthetique [--base chemin.db]
"""
import argparse
import csv
import io
import json
import random
import time
from datetime import datetime, timedelta, timezone

from shapely.geometry import Point

from ..config import charger_config
from . import base, controles, doublons, importation, score

GRAINE = 20260116


# ------------------------------------------------------------------ photos fictives
def photo_synthetique(graine, taille=256, qualite=90, exif=None) -> bytes:
    """Image fictive : un motif de couleurs aléatoire (différent pour chaque graine). Mêmes graine = même image."""
    import numpy as np
    from PIL import Image
    import io as _io
    motif = (np.random.default_rng(graine).random((8, 8, 3)) * 255).astype("uint8")
    img = Image.fromarray(motif).resize((taille, taille), Image.BICUBIC)
    bruit = np.random.default_rng(graine + 10**6).normal(0, 6, (taille, taille, 3))
    img = Image.fromarray(np.clip(np.asarray(img) + bruit, 0, 255).astype("uint8"))
    tampon = _io.BytesIO()
    img.save(tampon, "JPEG", quality=qualite, **({"exif": exif} if exif else {}))
    return tampon.getvalue()


def exif_fictif(lat, lon, date) -> bytes:
    from PIL import Image
    e = Image.Exif()
    e.get_ifd(0x8769)[36867] = date.strftime("%Y:%m:%d %H:%M:%S")
    gps = e.get_ifd(0x8825)
    gps[1], gps[3] = ("N" if lat >= 0 else "S"), ("E" if lon >= 0 else "W")
    gps[2], gps[4] = (abs(lat), 0, 0), (abs(lon), 0, 0)
    return e.tobytes()


# ------------------------------------------------------------------ choix de lieux
class Lieux:
    def __init__(self, rng, ref):
        self.rng, self.ref = rng, ref
        minx, miny, maxx, maxy = -1.60, 12.30, -1.45, 12.45
        self.boite = (minx, miny, maxx, maxy)

    def valide(self, lat, lon):
        p = Point(lon, lat)
        return bool(self.ref.secteur_de(lat, lon)) and not self.ref.eau.covers(p) and not self.ref.aeroport.covers(p)

    def tirer(self, test):
        minx, miny, maxx, maxy = self.boite
        while True:
            lon, lat = self.rng.uniform(minx, maxx), self.rng.uniform(miny, maxy)
            if test(lat, lon):
                return lat, lon

    def bon(self):
        return self.tirer(self.valide)

    def autour(self, lat, lon, metres=12):
        d = metres / 111_000
        while True:
            la, lo = lat + self.rng.uniform(-d, d), lon + self.rng.uniform(-d, d)
            if self.valide(la, lo):
                return la, lo

    def dans_eau(self):
        return self.tirer(lambda la, lo: self.ref.eau.covers(Point(lo, la)) and self.ref.dans_commune(la, lo))

    def sur_piste(self):
        return self.tirer(lambda la, lo: self.ref.aeroport.covers(Point(lo, la)))


# ------------------------------------------------------------------ génération
def generer(graine=GRAINE, maintenant=None) -> list[dict]:
    """~250 signalements d'application, dans l'ordre d'arrivée. Chaque entrée : cas, sig, photos, attendu.
    attendu : 'verifie' | 'pas_verifie' (rejeté ou à confirmer) | 'rejete' | 'libre'."""
    rng = random.Random(graine)
    now = maintenant or datetime.now(timezone.utc)
    ref = controles.reference()
    lieux = Lieux(rng, ref)
    sortie, compteur = [], [0]

    def ajouter(cas, lat, lon, attendu, enq, app, quand, photos=(), secteur="auto"):
        if secteur == "auto":
            s = ref.secteur_de(lat, lon) if abs(lat) <= 90 and abs(lon) <= 180 else None
            secteur = s[1] if s else None
        sortie.append({"cas": cas, "attendu": attendu, "photos": list(photos), "sig": {
            "lat": lat, "lon": lon, "secteur": secteur, "enqueteur": enq, "appareil": app,
            "horodatage": quand.isoformat(), "taille": rng.choice(["petit", "moyen", "grand"]),
            "nature": rng.choice(["ordures menagères", "gravats", "plastiques", "mixte"]),
            "caniveau": rng.random() < 0.3, "accessibilite": rng.choice(["camion", "tricycle", "difficile"])}})

    def photo(lat, lon, quand, avec_exif=True, decalage_m=0.0):
        compteur[0] += 1
        ex = exif_fictif(lat + decalage_m / 111_000, lon, quand) if avec_exif else None
        return photo_synthetique(graine + compteur[0], exif=ex)

    enqueteurs = [f"ENQ-{i:02d}" for i in range(1, 31)]
    appareil = lambda e: "APP-" + e[4:]  # noqa: E731
    bons = []
    # 1. de bons signalements autour de 45 vrais tas fictifs (1 à 4 enquêteurs distincts chacun)
    for _ in range(45):
        tas = lieux.bon()
        t0 = now - timedelta(days=rng.uniform(1, 30))
        for k, e in enumerate(rng.sample(enqueteurs, rng.choice([1, 2, 2, 3, 4]))):
            la, lo = lieux.autour(*tas)
            q = t0 + timedelta(hours=3 * k + rng.uniform(0, 2))
            ph = photo(la, lo, q, avec_exif=rng.random() < 0.6)
            ajouter("bon", la, lo, "verifie", e, appareil(e), q, [ph])
            bons.append(sortie[-1])
    # 2. même enquêteur qui revient le lendemain : pas une confirmation
    for b in rng.sample(bons, 20):
        la, lo = lieux.autour(b["sig"]["lat"], b["sig"]["lon"], 8)
        q = datetime.fromisoformat(b["sig"]["horodatage"]) + timedelta(days=rng.randint(1, 3))
        ajouter("doublon_meme_enqueteur", la, lo, "pas_verifie", b["sig"]["enqueteur"], b["sig"]["appareil"], q, [photo(la, lo, q)])
    # 3. photo réutilisée : copie recompressée/redimensionnée de la photo d'un autre signalement
    for b in rng.sample(bons, 15):
        la, lo = lieux.bon()
        q = now - timedelta(hours=rng.uniform(1, 40))
        e = rng.choice(enqueteurs)
        from PIL import Image
        img = Image.open(io.BytesIO(b["photos"][0])).resize((rng.choice([128, 180, 200]),) * 2)
        tampon = io.BytesIO()
        img.save(tampon, "JPEG", quality=rng.choice([35, 45, 60]))
        ajouter("photo_reutilisee", la, lo, "pas_verifie", e, appareil(e) + "-R", q, [tampon.getvalue()])
    # 4. EXIF incohérent : photo prise à ~5 km du point déclaré
    for _ in range(8):
        la, lo = lieux.bon(); q = now - timedelta(hours=rng.uniform(1, 40)); e = rng.choice(enqueteurs)
        ajouter("exif_incoherent", la, lo, "pas_verifie", e, appareil(e) + "-X", q, [photo(la, lo, q, True, 5000)])
    # 5. positions impossibles (aucune photo nécessaire)
    pieges = [("hors_commune", 12, lambda: (rng.uniform(13.5, 14.5), rng.uniform(1, 3))),
              ("dans_leau", 12, lieux.dans_eau), ("sur_la_piste", 10, lieux.sur_piste),
              ("zero_zero", 8, lambda: (0.0, 0.0)), ("lat_lon_inverses", 10, lambda: tuple(reversed(lieux.bon())))]
    for cas, n, tirer in pieges:
        for i in range(n):
            la, lo = tirer(); e = rng.choice(enqueteurs)
            ajouter(cas, la, lo, "rejete", e, f"APP-{cas}-{i}", now - timedelta(hours=rng.uniform(1, 40)),
                    [photo(la, lo, now)] if i % 2 else [], secteur=None)
    # 6. horodatage dans le futur
    for i in range(10):
        la, lo = lieux.bon(); e = rng.choice(enqueteurs)
        ajouter("futur", la, lo, "rejete", e, f"APP-FUTUR-{i}", now + timedelta(days=rng.randint(1, 60)))
    # 7. gonflage : un même appareil renvoie le même signalement 4 fois en quelques secondes
    for i in range(6):
        la, lo = lieux.bon(); q = now - timedelta(hours=rng.uniform(2, 40))
        for k in range(4):
            ajouter("gonflage" if k else "gonflage_premier", la, lo, "rejete" if k else "libre", "ENQ-GONFLEUR", f"APP-GONFLE-{i}", q + timedelta(seconds=k))
    # 8. rafale impossible : un appareil « se téléporte » toutes les 5 secondes
    q = now - timedelta(hours=5)
    for k in range(12):
        la, lo = lieux.bon()
        ajouter("rafale" if k else "rafale_premier", la, lo, "rejete" if k else "libre", "ENQ-RAFALE", "APP-RAFALE", q + timedelta(seconds=5 * k))
    return sortie


def fichiers_pieges(graine=GRAINE, maintenant=None):
    """Trois fichiers d'import : CSV correct (sans photo), CSV mal formé, GeoJSON sans photo. Renvoie des octets."""
    rng = random.Random(graine + 1)
    now = maintenant or datetime.now(timezone.utc)
    lieux = Lieux(rng, controles.reference())
    lignes = [lieux.bon() for _ in range(25)]
    tampon = io.StringIO()
    w = csv.writer(tampon)
    w.writerow(["lat", "lon", "enqueteur", "appareil", "horodatage"])
    for i, (la, lo) in enumerate(lignes):
        w.writerow([f"{la:.6f}", f"{lo:.6f}", f"IMP-{i % 5}", f"IMPAPP-{i}", (now - timedelta(days=1, minutes=i * 7)).isoformat()])
    mal = ("lat,lon,enqueteur\n12.35,-1.52,X\nceci n'est pas une ligne\n12.36;-1.5;Y;Z\n,,,\n"
           "abc,def,W\n" + f"{lignes[0][0]:.6f},{lignes[0][1]:.6f},OK\n").encode("utf-8")
    geo = {"type": "FeatureCollection", "features": [
        {"type": "Feature", "geometry": {"type": "Point", "coordinates": [lo, la]},
         "properties": {"enqueteur": f"GEO-{i % 4}", "appareil": f"GEOAPP-{i}", "horodatage": (now - timedelta(days=2, minutes=i)).isoformat()}}
        for i, (la, lo) in enumerate(lieux.bon() for _ in range(20))]}
    return tampon.getvalue().encode("utf-8"), mal, json.dumps(geo).encode("utf-8")


def peupler(conn, cfg=None, graine=GRAINE) -> dict:
    """Peuple la base avec le jeu synthétique. Renvoie un bilan avec les temps de traitement."""
    cfg = cfg or charger_config()
    ref = controles.reference()
    entrees = generer(graine)
    t0 = time.perf_counter()
    ecarts = 0
    for e in entrees:
        r = score.verifier_et_enregistrer(conn, e["sig"], e["photos"], ref, cfg, synthetique=True)
        att = e["attendu"]
        if (att == "verifie" and r["statut"] != "verifie") or (att == "rejete" and r["statut"] != "rejete") \
                or (att == "pas_verifie" and r["statut"] == "verifie"):
            ecarts += 1
    t_app = time.perf_counter() - t0
    for nom, contenu in zip(("bons.csv", "mal_forme.csv", "sans_photo.geojson"), fichiers_pieges(graine)):
        importation.importer(conn, nom, contenu, cfg, ref, synthetique=True)
    nb_dep = doublons.consolider(conn, cfg)
    return {"signalements_application": len(entrees), "temps_application_s": round(t_app, 2),
            "ecarts_avec_attendu": ecarts, "depotoirs": nb_dep, "par_statut": base.compter_par_statut(conn)}


def main():
    p = argparse.ArgumentParser(description="Peuple la base avec un jeu de signalements SYNTHÉTIQUES piégés.")
    p.add_argument("--base", help="fichier SQLite (défaut : data/oregdo.db)")
    a = p.parse_args()
    conn = base.ouvrir(a.base)
    if conn.execute("SELECT COUNT(*) FROM signalement WHERE synthetique=1").fetchone()[0]:
        print("La base contient déjà des signalements synthétiques : rien n'a été ajouté (supprimez le fichier ou utilisez --base).")
        return
    print(json.dumps(peupler(conn), ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
