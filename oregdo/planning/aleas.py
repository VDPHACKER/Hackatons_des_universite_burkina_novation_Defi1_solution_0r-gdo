"""Quatre aléas du jury : chacun transforme le scénario ; le plan est ensuite recalculé par plan.calculer_plan."""
from . import validation
from .scenario import Scenario

class MessageAvecLot(str):
    """Message en français portant en plus le détail du lot de signalements vérifiés (attribut `lot`)."""
    lot = None


TYPES = ("panne_camion", "saison_pluies", "nouveau_quartier", "signalements_pieges")


def appliquer(sc: Scenario, type_alea: str, params: dict | None = None) -> tuple:
    """Renvoie (nouveau_scenario, message_en_français). Lève ValueError pour un aléa ou des paramètres invalides."""
    if params is None:
        params = {}
    if not isinstance(params, dict):
        raise ValueError("Les paramètres de l'aléa doivent être un objet JSON.")
    n = validation.nombre
    if type_alea == "panne_camion":
        dispo = sc.camions_disponibles()
        brut = params.get("camions")
        if isinstance(brut, (list, tuple)):             # identifiants précis de camions
            nouveaux = [n("identifiant de camion", c, 0, sc.camions_nombre - 1, entier=True) for c in brut]
            if len(set(nouveaux)) != len(nouveaux):
                raise ValueError("La liste de camions en panne contient des doublons.")
        else:                                           # un nombre : combien de camions tombent en panne
            combien = n("nombre de camions en panne", brut if brut is not None else params.get("nombre", 1), 0, None, entier=True)
            if combien > len(dispo):
                raise ValueError(f"Impossible de mettre {combien} camions en panne : {len(dispo)} seulement sont disponibles.")
            nouveaux = dispo[:combien]
        sc2 = sc.modifie(camions_en_panne=sorted(set(sc.camions_en_panne) | set(nouveaux)))
        sc2.valider()
        return sc2, f"{len(nouveaux)} camion(s) en panne : {len(sc2.camions_disponibles())} restent disponibles."
    if type_alea == "saison_pluies":
        actif = params.get("actif", True)
        if not isinstance(actif, bool):
            raise ValueError("« actif » doit valoir vrai ou faux.")
        return sc.modifie(saison_pluies=actif), ("Saison des pluies activée : pistes et zones inondables pénalisées."
                                                 if actif else "Saison des pluies désactivée.")
    if type_alea == "nouveau_quartier":
        for cle in ("population", "polygone"):
            if cle not in params:
                raise ValueError(f"Nouveau quartier : paramètre « {cle} » manquant.")
        q, avertissements = validation.valider_quartier(params, len(sc.nouveaux_quartiers))
        message = f"Quartier « {q['nom']} » ajouté ({int(q['population'])} habitants) avec ses sites candidats."
        return sc.modifie(nouveaux_quartiers=sc.nouveaux_quartiers + [q]), " ".join([message] + avertissements)
    if type_alea == "signalements_pieges":
        # Branchement sur le VRAI pipeline de vérification (module de vérification) : mêmes contrôles que l'application.
        from ..verification import lot
        recus = params.get("signalements")
        maxi = validation.limites().pieges_max
        if recus is not None and (not isinstance(recus, list) or len(recus) > maxi):
            raise ValueError(f"« signalements » doit être une liste d'au plus {maxi} signalements.")
        generer = params.get("generer", params.get("nombre") if recus is None else None)
        if generer is not None:
            generer = n("nombre de signalements à générer", generer, 0, maxi, entier=True)
        if recus is None and generer is None:
            generer = 10
        graine = params.get("graine")
        if graine is not None:
            graine = n("graine", graine, 0, 10**9, entier=True)
        lot_res = lot.verifier_pieges(recus, generer, graine=graine)
        n, r = len(lot_res["resultats"]), lot_res["resume"]
        # Aucun effet sur le plan : seuls les dépotoirs au statut « vérifié » de la base y entrent.
        message = MessageAvecLot(f"{n} signalement(s) piégé(s) passés par le pipeline : {r['rejetes']} rejeté(s), "
                                 f"{r['a_confirmer']} à confirmer, {r['verifies']} vérifié(s). Seuls les vérifiés entrent dans le plan.")
        message.lot = lot_res
        return sc.modifie(signalements_pieges_recus=sc.signalements_pieges_recus + n), message
    raise ValueError(f"Aléa inconnu : « {type_alea} ». Types possibles : {', '.join(TYPES)}.")
