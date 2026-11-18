"""Étalonnage : compare ce que les pré-collecteurs ont réellement collecté (table `collecte`) à ce que suppose le modèle.

Ce module ne modifie jamais les paramètres : il mesure l'écart et dit quoi faire. L'ajustement du fichier `commune_config.yaml` reste
une décision humaine (la mairie), car quelques collectes d'un seul point ne suffisent pas à changer une hypothèse pour toute la commune.
"""
from ..config import charger_config

MIN_COLLECTES = 10        # [H] en dessous, trop peu de mesures pour conclure
MIN_POINTS = 3            # [H] et au moins 3 points de regroupement différents, sinon on mesure un seul quartier
TOLERANCE = 0.20          # [H] écart relatif jugé normal


def etalonner(conn, commune: str | None = None) -> dict:
    cfg = charger_config(commune) if commune else charger_config()
    d = cfg.demographie
    hab_par_menage = d.population / d.menages
    modele = d.production_kg_hab_jour * hab_par_menage                 # kg de déchets produits par ménage et par jour, selon le modèle
    lignes = [dict(r) for r in conn.execute("SELECT point, kg, nb_menages FROM collecte WHERE nb_menages > 0 AND kg > 0")]
    n, kg, menages = len(lignes), sum(x["kg"] for x in lignes), sum(x["nb_menages"] for x in lignes)
    points = {}
    for x in lignes:
        p = points.setdefault(x["point"] or "non précisé", {"point": x["point"] or "non précisé", "collectes": 0, "kg": 0.0, "menages": 0})
        p["collectes"] += 1; p["kg"] += x["kg"]; p["menages"] += x["nb_menages"]
    detail = sorted(({"point": p["point"], "collectes": p["collectes"], "kg_par_menage": round(p["kg"] / p["menages"], 2)} for p in points.values()),
                    key=lambda p: -p["collectes"])
    sortie = {"collectes": n, "points": len(points), "kg_total": round(kg, 1), "menages_servis": menages, "kg_par_menage_modele": round(modele, 2),
              "parametre": "demographie.production_kg_hab_jour", "valeur_actuelle": d.production_kg_hab_jour, "detail": detail[:10],
              "seuils": {"collectes_min": MIN_COLLECTES, "points_min": MIN_POINTS, "tolerance_pct": int(TOLERANCE * 100)}}
    if not n:
        return {**sortie, "suffisant": False, "kg_par_menage_observe": None, "ecart_pct": None,
                "avis": "Aucune collecte saisie : l'étalonnage commence dès que les pré-collecteurs enregistrent leurs tournées (poids et ménages servis)."}
    obs = kg / menages
    ecart = (obs - modele) / modele
    sortie.update(kg_par_menage_observe=round(obs, 2), ecart_pct=round(ecart * 100, 1), suffisant=n >= MIN_COLLECTES and len(points) >= MIN_POINTS)
    if not sortie["suffisant"]:
        sortie["avis"] = (f"Trop peu de mesures pour conclure ({n} collecte(s) sur {len(points)} point(s) ; il en faut au moins {MIN_COLLECTES} "
                          f"sur {MIN_POINTS} points). Écart provisoire : {ecart * 100:+.0f} %. Continuer la saisie.")
    elif abs(ecart) <= TOLERANCE:
        sortie["avis"] = f"Le modèle est cohérent avec le terrain : {obs:.2f} kg par ménage et par jour observés pour {modele:.2f} supposés (écart {ecart * 100:+.0f} %)."
    else:
        suggeree = round(d.production_kg_hab_jour * obs / modele, 2)
        sortie["valeur_suggeree"] = suggeree
        sortie["avis"] = (f"Écart de {ecart * 100:+.0f} % : {obs:.2f} kg par ménage et par jour observés contre {modele:.2f} supposés. Si l'écart se confirme "
                          f"sur plusieurs semaines et plusieurs points, ajuster `production_kg_hab_jour` de {d.production_kg_hab_jour} à environ {suggeree} "
                          "dans commune_config.yaml, puis « Relire le fichier de paramètres ». La pré-collecte ne mesure que ce qui sort du ménage : "
                          "elle sous-estime la production si une part est brûlée ou enfouie sur place.")
    return sortie
