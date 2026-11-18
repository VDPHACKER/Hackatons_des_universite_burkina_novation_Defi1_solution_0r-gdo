"""Calcule les scénarios du rapport (plan de gestion + simulation de 60 jours) et écrit livrables/scenarios_resultats.json.

    .venv\\Scripts\\python.exe scripts\\scenarios_rapport.py

Tous les paramètres viennent de packs/ouaga/commune_config.yaml ; chaque scénario ne change que ce qui est dit dans `modifs`.
Les chiffres sont des résultats de SIMULATION sur données fictives et hypothèses [H] : ils comparent des scénarios, ils ne prédisent rien.
"""
import json
import sys
import time
from pathlib import Path

RACINE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RACINE))
from oregdo.planning import arrondissement  # noqa: E402
from oregdo.planning.plan import calculer_plan_detaille  # noqa: E402
from oregdo.planning.scenario import Scenario  # noqa: E402
from oregdo.simulation.modele import simuler  # noqa: E402

JOURS = 60
SCENARIOS = [
    ("reference", "Situation de référence (paramètres du pack)", {}),
    ("camions_moins", "Moins de camions : 30 au lieu de 40", {"camions_nombre": 30}),
    ("camions_plus", "Plus de camions : 60 au lieu de 40", {"camions_nombre": 60}),
    ("abonnement_70", "Abonnement porté à 70 % des ménages (40 camions)", {"taux_abonnement": 0.70}),
    ("abonnement_70_camions_60", "Abonnement 70 % et 60 camions", {"taux_abonnement": 0.70, "camions_nombre": 60}),
    ("passage_2j", "Un passage tous les 2 jours au lieu de tous les jours", {"frequence_collecte_jours": 2}),
    ("tri_60", "Valorisation : 60 % des ménages trient et revendent", {"taux_tri": 0.6}),
    ("pluies", "Saison des pluies (pistes coupées, zones inondables)", {"saison_pluies": True}),
    ("pannes", "10 camions en panne sur 40", {"camions_en_panne": list(range(10))}),
    ("population_x1_6", "Population à 4 millions d'habitants (x1,6)", {"facteur_population": 1.6}),
    ("combine", "Plan combiné : 60 camions, abonnement 70 %, tri 60 %", {"camions_nombre": 60, "taux_abonnement": 0.70, "taux_tri": 0.6}),
]
CLES_KPI = ("tonnes_produites_j", "tonnes_valorisees_j", "tonnes_evacuees_j", "tonnes_non_evacuees_j", "taux_fuite", "taux_couverture_production",
            "couverture_population", "nb_pr", "camions_utilises", "distance_km", "cout_collecte_fcfa", "cout_par_tonne_fcfa", "temps_calcul_s")


def main():
    base = Scenario.depuis_config()
    sortie = {"jours_simulation": JOURS, "scenarios": []}
    for cle, titre, modifs in SCENARIOS:
        sc = base.modifie(**modifs)
        sc.valider()
        t0 = time.perf_counter()
        det = calculer_plan_detaille(sc)
        kpi = det["plan"]["kpi"]
        sim = simuler(sc, jours=JOURS)
        diag = sim["diagnostic"]
        ligne = {"cle": cle, "titre": titre, "modifs": modifs,
                 "kpi": {k: (kpi[k] if k in kpi else det["plan"].get(k)) for k in CLES_KPI},
                 "simulation": {k: diag[k] for k in ("tendance_stock", "stock_initial_tonnes", "stock_final_tonnes", "variation_stock_t_par_jour",
                                                     "camions_supplementaires_pour_stabiliser", "stable")},
                 "duree_calcul_s": round(time.perf_counter() - t0, 1)}
        if cle == "reference":
            ligne["arrondissements"] = arrondissement.tableau(det, sc)["arrondissements"]
        sortie["scenarios"].append(ligne)
        print(f"{cle:16s} couverture {kpi['taux_couverture_production']:.2f}  fuite {kpi['taux_fuite']:.3f}  évacué {kpi['tonnes_evacuees_j']:7.1f} t/j  "
              f"stock final {diag['stock_final_tonnes']:8.1f} t  ({ligne['duree_calcul_s']} s)")
    chemin = RACINE / "livrables" / "scenarios_resultats.json"
    chemin.write_text(json.dumps(sortie, ensure_ascii=False, indent=1), encoding="utf-8")
    print("écrit :", chemin)


if __name__ == "__main__":
    main()
