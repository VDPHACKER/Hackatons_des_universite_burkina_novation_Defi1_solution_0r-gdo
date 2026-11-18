"""Fabrique de photos de test (images synthétiques avec ou sans EXIF)."""
import io

import numpy as np
from PIL import Image


def jpeg(graine, taille=256, qualite=90, exif=None):
    rng = np.random.default_rng(graine)
    petit = (rng.random((8, 8, 3)) * 255).astype("uint8")
    img = Image.fromarray(petit).resize((taille, taille), Image.BICUBIC)
    tampon = io.BytesIO()
    img.save(tampon, "JPEG", quality=qualite, **({"exif": exif} if exif else {}))
    return tampon.getvalue()


def exif_octets(lat, lon, date):
    e = Image.Exif()
    e.get_ifd(0x8769)[36867] = date.strftime("%Y:%m:%d %H:%M:%S")
    gps = e.get_ifd(0x8825)
    gps[1], gps[3] = ("N" if lat >= 0 else "S"), ("E" if lon >= 0 else "W")
    gps[2], gps[4] = (abs(lat), 0, 0), (abs(lon), 0, 0)
    return e.tobytes()


_compteur = [1000]


def photo_neuve():
    """Une photo jamais vue (graine qui change à chaque appel)."""
    _compteur[0] += 1
    return jpeg(_compteur[0])
