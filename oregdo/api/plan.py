"""Routeur FastAPI : scénario, plan, aléas, simulation, comparaison, suggestions (messages en français)."""
import json
import logging
import os
import threading
import time

import numpy as np
from fastapi import APIRouter, Body, Depends, HTTPException
from fastapi.responses import JSONResponse

from ..planning import aleas, validation
from ..securite import exiger_roles

exiger_mairie = exiger_roles("mairie")     # pilotage : scénario, plan, simulation (l'admin passe toujours)
from ..planning import arrondissement
from ..planning.plan import calculer_plan, calculer_plan_detaille
from ..planning.scenario import Scenario
from ..planning.suggestions import suggerer
from ..simulation.comparaison import comparer
from ..simulation.modele import simuler

router = APIRouter(tags=["plan et simulation"])
_verrou = threading.RLock()
_etat = {"scenario": None, "plan": None, "detail": None}


def reinitialiser() -> None:
    """Revient au scénario de référence du config (utile aux tests et au bouton « réinitialiser »)."""
    with _verrou:
        _etat["scenario"], _etat["plan"] = Scenario.depuis_config(), None


def _chauffer_le_reseau() -> None:
    """Graphe routier : distances entre points fixes (sites, dépôt, CET), hors saison et en saison des pluies. Premier lancement :
    ~40 s, ensuite relu depuis data/cache. Sans cela, le premier aléa « pluies » du jury attendrait ce calcul."""
    from ..planning import donnees, graphe_routier
    g = graphe_routier.charger()
    if g is not None:
        base = donnees.charger()
        g.chauffer(np.vstack([base.sites_xy, base.depot_xy, base.cet_xy]))


def prechauffer() -> None:
    """Calcule le plan de référence au démarrage : couches, index spatiaux et OR-Tools sont chargés avant la 1re requête."""
    with _verrou:
        if _etat["plan"] is None:
            _chauffer_le_reseau()
            _recalculer()


def _prechauffer_en_arriere_plan() -> None:
    if os.environ.get("OREGDO_PRECHAUFFAGE", "1") == "0":
        return

    def tache():
        try:
            prechauffer()
            calculer_plan(_scenario().modifie(saison_pluies=True))     # chauffe aussi la saison des pluies (1re demande du jury)
            comparer(Scenario.depuis_config(), _scenario(), None)   # comparaison 90 jours : sinon ~9 s au premier appel
        except Exception:   # le préchauffage ne doit jamais empêcher le serveur de démarrer
            logging.getLogger("oregdo").exception("Préchauffage du plan échoué")

    threading.Thread(target=tache, name="prechauffage-plan", daemon=True).start()


def _scenario() -> Scenario:
    if _etat["scenario"] is None:
        reinitialiser()
    return _etat["scenario"]


def _json(contenu, code: int = 200) -> JSONResponse:
    """Sérialise en convertissant les types numpy (np.int64...) en types natifs."""
    brut = json.dumps(contenu, default=lambda o: o.item() if isinstance(o, np.generic) else str(o))
    return JSONResponse(content=json.loads(brut), status_code=code)


ERREURS_ENTREE = (ValueError, TypeError, KeyError, AttributeError, OverflowError, IndexError)


def _erreur(e: Exception, code: int = 422):
    """Entrée absurde : 422 avec un message en français (jamais de 500 pour une valeur invalide)."""
    detail = str(e) if isinstance(e, ValueError) else f"Paramètres invalides ({type(e).__name__}) : vérifiez les types et les noms des champs."
    raise HTTPException(status_code=code, detail=detail)


def _decimal(texte: str):
    """Paramètre d'URL -> nombre ; « nan », « inf » ou du texte sont refusés par validation.nombre."""
    try:
        return float(texte)
    except (TypeError, ValueError):
        raise ValueError(f"Paramètre d'URL non numérique : « {texte} ».") from None


def _objet(corps, nom: str = "corps") -> dict:
    if corps is None:
        return {}
    if not isinstance(corps, dict):
        raise HTTPException(status_code=422, detail=f"Le {nom} doit être un objet JSON.")
    return corps


def _recalculer(sc: Scenario | None = None) -> dict:
    """Calcule le plan d'abord ; le scénario et le plan ne sont mémorisés que si le calcul réussit."""
    with _verrou:
        sc = sc or _scenario()
        detail = calculer_plan_detaille(sc)
        plan = detail["plan"]
        _etat["scenario"], _etat["plan"], _etat["detail"] = sc, plan, detail     # le détail sert au découpage par arrondissement
        return plan


@router.get("/commune")
def lire_commune():
    """La commune servie par cette instance (variable OREGDO_COMMUNE) : l'interface s'adapte, rien n'y est codé en dur."""
    from ..config import COMMUNE_DEFAUT, charger_config
    from ..geo import couche
    cfg = charger_config()
    x0, y0, x1, y1 = (float(v) for v in couche("commune").total_bounds)
    etendue = max(x1 - x0, (y1 - y0) / 0.9)
    ouaga = COMMUNE_DEFAUT == "ouaga"
    return _json({
        "code": COMMUNE_DEFAUT, "nom": cfg.commune.nom, "marque": getattr(cfg.commune, "marque", "Orẽgdo"), "population": cfg.demographie.population, "menages": cfg.demographie.menages,
        "centre": [-1.53, 12.37] if ouaga else [round((x0 + x1) / 2, 4), round((y0 + y1) / 2, 4)],
        "zoom": 10.5 if ouaga else round(max(8.0, min(13.0, 9.6 - np.log2(max(etendue, 0.01) / 0.3))), 1),
        "bbox": [round(x0, 4), round(y0, 4), round(x1, 4), round(y1, 4)],
        "pack": "data/pack/" if ouaga else f"packs/{COMMUNE_DEFAUT}/",          # couches du pack (GeoJSON)
        "fond": "data/pack/fond/" if ouaga else f"data/packs/{COMMUNE_DEFAUT}/fond/",   # fond de carte OSM
        "camions": cfg.planification.camions.nombre, "budget_pr_fcfa": cfg.planification.budget_pr_fcfa,
    })


@router.get("/scenario")
def lire_scenario():
    return _json({"scenario": _scenario().to_dict(), "reference": Scenario.depuis_config().to_dict()})


@router.put("/scenario", dependencies=[Depends(exiger_mairie)])
def modifier_scenario(modifications: dict = Body(...)):
    """Modifie des paramètres (population, abonnement, camions, fréquence, budget, saison_pluies...)."""
    try:
        with _verrou:
            nouveau = _scenario().modifie(**_objet(modifications))
            nouveau.valider()
            _etat["scenario"], _etat["plan"] = nouveau, None
    except ERREURS_ENTREE as e:
        _erreur(e)
    return _json({"message": "Scénario mis à jour ; le plan sera recalculé.", "scenario": _etat["scenario"].to_dict()})


@router.get("/plan")
def lire_plan():
    try:
        with _verrou:
            return _json(_etat["plan"] or _recalculer())
    except ERREURS_ENTREE as e:
        _erreur(e)


def _detail() -> dict:
    with _verrou:
        if _etat["plan"] is None or _etat.get("detail") is None:
            _recalculer()
        return _etat["detail"]


@router.get("/plan/arrondissements")
def lire_arrondissements():
    """Les 12 arrondissements côte à côte (du moins bien desservi au mieux desservi). Contours synthétiques, dits comme tels."""
    try:
        with _verrou:
            return _json(arrondissement.tableau(_detail(), _scenario()))
    except ERREURS_ENTREE as e:
        _erreur(e)


@router.get("/plan/arrondissement/{code}")
def lire_plan_arrondissement(code: str):
    """Plan de gestion d'un arrondissement : indicateurs, contour, points de regroupement, dépotoirs, tournées qui le traversent."""
    try:
        with _verrou:
            return _json(arrondissement.plan_arrondissement(_detail(), _scenario(), code))
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except ERREURS_ENTREE as e:
        _erreur(e)


KPI_COMPARES = ("tonnes_produites_j", "tonnes_valorisees_j", "tonnes_evacuees_j", "tonnes_fuite_j", "taux_fuite", "taux_couverture_production",
                "couverture_population", "nb_pr", "camions_utilises", "camions_disponibles", "distance_km", "cout_collecte_fcfa", "cout_par_tonne_fcfa",
                "cout_investissement_pr_fcfa")


@router.post("/plan/comparer", dependencies=[Depends(exiger_mairie)])
def comparer_scenarios(corps: dict = Body(...)):
    """Calcule le plan de 1 à 4 scénarios côte à côte. Chaque scénario est une liste de modifications du scénario de RÉFÉRENCE du pack
    (mêmes noms que PUT /scenario). N'altère ni le scénario courant ni le plan courant."""
    try:
        corps = _objet(corps)
        liste = corps.get("scenarios")
        if not isinstance(liste, list) or not 1 <= len(liste) <= 4:
            raise ValueError("« scenarios » doit être une liste de 1 à 4 scénarios (chacun : un objet de modifications).")
        base, sortie, debut = Scenario.depuis_config(), [], time.perf_counter()
        with _verrou:                     # le graphe routier et ses caches ne sont pas faits pour des calculs simultanés
            for i, mods in enumerate(liste, 1):
                sc = base.modifie(**_objet(mods, f"scénario {i}"))
                sc.valider()
                plan = calculer_plan(sc)
                sortie.append({"numero": i, "modifications": mods, "kpi": {k: plan["kpi"].get(k) for k in KPI_COMPARES}, "temps_calcul_s": plan["temps_calcul_s"]})
        return _json({"scenarios": sortie, "temps_total_s": round(time.perf_counter() - debut, 2)})
    except ERREURS_ENTREE as e:
        _erreur(e)


@router.post("/config/recharger", dependencies=[Depends(exiger_mairie)])
def recharger_la_configuration():
    """Relit le fichier de paramètres documenté (packs/<commune>/commune_config.yaml) sans redémarrer le serveur : le scénario courant
    revient aux valeurs du fichier et le plan est recalculé à la prochaine demande."""
    from ..config import COMMUNE_DEFAUT, charger_config
    try:
        charger_config.__wrapped__(COMMUNE_DEFAUT)     # lit et valide le fichier SANS toucher au cache : s'il est invalide, l'ancien état est conservé
    except Exception as e:
        raise HTTPException(status_code=422, detail=f"Le fichier de paramètres n'a pas pu être relu (l'ancien est conservé) : {e}")
    with _verrou:
        charger_config.cache_clear()
        reinitialiser()
    return _json({"message": "Paramètres relus depuis le fichier. Le plan sera recalculé à la prochaine demande.", "scenario": _scenario().to_dict()})


@router.post("/plan/recalculer", dependencies=[Depends(exiger_mairie)])
def recalculer():
    try:
        plan = _recalculer()
    except ERREURS_ENTREE as e:
        _erreur(e)
    return _json({**plan, "message": f"Plan recalculé en {plan['temps_calcul_s']} s."})


@router.post("/alea", dependencies=[Depends(exiger_mairie)])      # épreuve en direct : la mairie pilote, l'admin passe toujours
def appliquer_alea(corps: dict = Body(...)):
    """Applique un aléa (panne_camion, saison_pluies, nouveau_quartier, signalements_pieges) puis recalcule."""
    try:
        with _verrou:
            avant = _etat["plan"]["empreinte"] if _etat["plan"] else None
            corps = _objet(corps)
            if not isinstance(corps.get("type"), str):
                raise ValueError("Le champ « type » de l'aléa est obligatoire (texte).")
            nouveau, message = aleas.appliquer(_scenario(), corps["type"], corps.get("params"))
            nouveau.valider()
            plan = _recalculer(nouveau)
    except ERREURS_ENTREE as e:
        _erreur(e)
    reponse = {"message": str(message), "plan_modifie": avant is None or avant != plan["empreinte"], "plan": plan}
    if getattr(message, "lot", None):                         # aléa « signalements_pieges » : verdict du vrai pipeline
        reponse.update(resultats=message.lot["resultats"], resume=message.lot["resume"])
    return _json(reponse)


@router.post("/simulation/run", dependencies=[Depends(exiger_mairie)])
def lancer_simulation(corps: dict = Body(default_factory=dict)):
    try:
        corps = _objet(corps)
        sc = _scenario().modifie(**_objet(corps.get("scenario"), "champ « scenario »"))
        resultat = simuler(sc, corps.get("jours"))
    except ERREURS_ENTREE as e:
        _erreur(e)
    return _json(resultat)


@router.get("/simulation/comparaison", dependencies=[Depends(exiger_mairie)])   # calcul long : jamais ouvert aux anonymes
def comparaison(jours: str | None = None):
    """Plan cible (valeurs du config) contre scénario courant, même graine ; résultats mémorisés."""
    try:
        n = None if jours is None else validation.nombre("jours", _decimal(jours), 1, None, entier=True)
        return _json(comparer(Scenario.depuis_config(), _scenario(), n))
    except ERREURS_ENTREE as e:
        _erreur(e)


@router.get("/suggestions/emplacements")
def suggestions_emplacements(n: str = "10"):
    try:
        n = validation.nombre("n", _decimal(n), 1, 100, entier=True)
        return _json(suggerer(_scenario(), n))
    except ERREURS_ENTREE as e:
        _erreur(e)


_prechauffer_en_arriere_plan()
