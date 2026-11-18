"""Fabrique les icônes de l'application à partir du logo Orẽgdo (web/icons/logo-source.png).

    python scripts/construire_icones.py

Produit dans web/icons/ : logo.png (logo complet), logo-entete.png (sans le slogan, pour l'en-tête),
icon-192.png et icon-512.png (installation), icon-maskable-512.png (Android : logo dans la zone sûre de 80 %),
apple-touch-icon.png (iPhone, 180 px) et favicon-48.png (onglet du navigateur).
"""
from pathlib import Path

from PIL import Image

ICONES = Path(__file__).resolve().parents[1] / "web" / "icons"
BLANC = (255, 255, 255, 255)


def sur_fond(logo: Image.Image, cote: int, part: float) -> Image.Image:
    """Logo centré sur un carré blanc, occupant `part` du côté (marge pour les masques ronds des lanceurs)."""
    fond = Image.new("RGBA", (cote, cote), BLANC)
    l = logo.copy()
    l.thumbnail((int(cote * part), int(cote * part)), Image.LANCZOS)
    fond.alpha_composite(l, ((cote - l.width) // 2, (cote - l.height) // 2))
    return fond.convert("RGB")


def blanchir(im: Image.Image) -> Image.Image:
    """Le fond du logo fourni est gris très clair (≈ 252) : on le ramène au blanc pur, en fondu, pour qu'il ne forme pas
    un carré visible sur le fond blanc des icônes. Les couleurs du dessin (vert, ocre) ne sont pas touchées."""
    import numpy as np
    a = np.asarray(im, dtype=np.float32)
    mini = a[..., :3].min(axis=2, keepdims=True)
    f = np.clip((mini - 236) / (250 - 236), 0, 1)                    # 0 sous 236, 1 au-dessus de 250
    a[..., :3] = a[..., :3] * (1 - f) + 255 * f
    return Image.fromarray(a.round().astype(np.uint8), "RGBA")


def main() -> None:
    source = blanchir(Image.open(ICONES / "logo-source.png").convert("RGBA"))
    l, h = source.size
    complet = source.copy()
    complet.thumbnail((480, 480), Image.LANCZOS)
    complet.convert("RGB").save(ICONES / "logo.png", optimize=True)
    # Sans le slogan (bas de l'image) : le cercle, le monument et le nom restent lisibles en petit.
    sans_slogan = source.crop((0, 0, l, int(h * 0.835)))
    sur_fond(sans_slogan, 128, 0.96).save(ICONES / "logo-entete.png", optimize=True)
    for cote in (192, 512):
        sur_fond(source, cote, 0.94).save(ICONES / f"icon-{cote}.png", optimize=True)
    sur_fond(source, 512, 0.78).save(ICONES / "icon-maskable-512.png", optimize=True)
    sur_fond(source, 180, 0.92).save(ICONES / "apple-touch-icon.png", optimize=True)
    sur_fond(sans_slogan, 48, 1.0).save(ICONES / "favicon-48.png", optimize=True)
    for f in sorted(ICONES.glob("*.png")):
        print(f"{f.name:28} {Image.open(f).size}  {f.stat().st_size // 1024} Ko")


if __name__ == "__main__":
    main()
