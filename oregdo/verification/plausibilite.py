"""Contrôle « photo plausible » : une heuristique simple, PAS un classifieur de contenu.

Elle écarte seulement les images manifestement fabriquées ou inutilisables : trop petites, unies, floues,
ou faites de bruit pur (pixels aléatoires). Elle NE SAIT PAS dire si la photo montre un dépotoir : une
photo de chat, ou une image de blocs de couleurs aléatoires, peut être jugée « plausible ».
Le classifieur d'image optionnel (controles.CLASSIFIEUR) reste le seul moyen de juger le contenu.
Une photo non plausible compte comme ABSENTE pour le plafond « sans photo » et pour la corroboration.
"""
import numpy as np

COTE_ANALYSE = 256


def mesurer(img) -> dict:
    """Mesures sur le niveau de gris : plus petit côté, écart-type, bruit, netteté. `img` est une image Pillow."""
    largeur, hauteur = img.size
    gris = img.convert("L")
    vignette = np.asarray(gris.resize((64, 64)), dtype=float)
    # Bruit et netteté mesurés sur un carré central à la résolution d'origine (le bruit se voit pixel par pixel).
    c = min(COTE_ANALYSE, largeur, hauteur)
    x0, y0 = (largeur - c) // 2, (hauteur - c) // 2
    zone = np.asarray(gris.crop((x0, y0, x0 + c, y0 + c)), dtype=float)
    ecart = float(zone.std())
    variation = 0.0
    if c > 1:
        variation = float((np.abs(np.diff(zone, axis=0)).mean() + np.abs(np.diff(zone, axis=1)).mean()) / 2)
    return {"cote_min": min(largeur, hauteur), "ecart_type": float(vignette.std()),
            "bruit": variation / ecart if ecart > 1e-6 else 0.0, "nettete": variation}


def juger(photo: dict, cfg) -> tuple[bool, str]:
    """(plausible, raison) pour une photo analysée (dict de controles.analyser_photo)."""
    p = cfg.verification.photo_plausible
    if "empreinte" not in photo:
        return False, "photo illisible"
    if not p.actif:
        return True, "contrôle de plausibilité désactivé"
    m = photo.get("mesures") or {}
    if m.get("cote_min", 0) < p.cote_min_px:
        return False, f"image trop petite ({m.get('cote_min')} px, minimum {p.cote_min_px})"
    if m.get("ecart_type", 0) < p.ecart_type_min:
        return False, "image quasi unie (aucun détail)"
    if m.get("bruit", 0) > p.bruit_max:
        return False, "image faite de bruit aléatoire (pas une vraie photo)"
    if m.get("nettete", 0) < p.nettete_min:
        return False, "image trop floue ou trop lisse"
    return True, "photo plausible (taille, contraste, netteté et bruit corrects ; contenu non jugé)"
