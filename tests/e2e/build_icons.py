r"""Génère les icônes PWA (PNG) avec Pillow. Usage : .venv\Scripts\python.exe -I tests/e2e/build_icons.py"""
from pathlib import Path
from PIL import Image, ImageDraw

DST = Path(__file__).resolve().parents[2] / "web" / "icons"
DST.mkdir(parents=True, exist_ok=True)


def icone(n, marge):
    im = Image.new("RGBA", (n, n), (11, 92, 58, 255))
    d = ImageDraw.Draw(im)
    c = n / 2
    r = n * (0.5 - marge)
    d.ellipse([c - r, c - r, c + r, c + r], fill=(255, 255, 255, 255))
    # une feuille stylisée : losange + tige
    s = r * 0.62
    d.polygon([(c, c - s), (c + s * 0.8, c), (c, c + s), (c - s * 0.8, c)], fill=(11, 92, 58, 255))
    d.line([(c, c + s * 1.0), (c, c - s * 0.7)], fill=(255, 255, 255, 255), width=max(2, n // 40))
    return im


for n in (192, 512):
    icone(n, 0.12).save(DST / f"icon-{n}.png")
icone(512, 0.25).save(DST / "icon-maskable-512.png")
print("ok")
