"""Modèle multi-agents Mesa au pas journalier (reproductible par graine)."""
import math
import time

import mesa
import numpy as np

from ..config import COMMUNE_DEFAUT, charger_config
from ..planning import couts as modele_couts
from ..planning import depotoirs as acces_depotoirs
from ..planning import reseau, validation
from ..planning.parametres import moteur
from ..planning.plan import PLAN_CIBLE, calculer_plan_detaille
from ..planning.scenario import Scenario
from .agents import Brigade, Depotoir, Ilot, Mairie, PointRegroupement, PreCollecteurs

JOURS_PAR_MOIS = 30   # convention de facturation de l'abonnement mensuel
CUMULS = ("produit", "collecte", "fui", "caniveau", "brule", "recettes_abonnement", "recettes_amendes",
          "amendes_emises_fcfa", "nb_amendes", "dep_carburant", "dep_personnel", "dep_vehicules", "dep_entretien",
          "dep_pr", "dep_brigade")


class ModeleOregdo(mesa.Model):
    def __init__(self, sc: Scenario, graine: int | None = None, commune: str = COMMUNE_DEFAUT, plan: dict | None = None):
        self.cfg = charger_config(commune)
        super().__init__(rng=self.cfg.simulation.graine if graine is None else graine)
        self.sc, self.p, self.jours_par_mois, self.commune = sc, moteur(self.cfg), JOURS_PAR_MOIS, commune
        self.jour = 0
        det = plan or calculer_plan_detaille(sc, commune)
        self.plan_kpi, self.d, self.plan_pr = det["plan"]["kpi"], det["donnees"], det["pr"]
        self.capacite_plan_kg = det["tournees"].kg_collectes
        self.capacite_depotoirs_kg = det["tournees"].kg_depotoirs_collectes   # part du plan réservée aux dépotoirs
        self.couts_plan = det["couts"]
        self.investissement_pr = det["pr"].cout_fcfa
        self.decisions, self.camions_achetes, self.investissement_camions, self.stock_dernier_examen = [], 0, 0.0, None   # décisions de la mairie
        self._init_flotte(sc, det)
        mo = self.cfg.demographie.modes_evacuation
        # Part du déchet non collecté qui part en fossé/caniveau (RGPH : fossé 4,9 % / (1 - ramassage privé)).
        self.part_caniveau = getattr(mo, "fosse_caniveau", 0.0) / (1 - mo.ramassage_prive)
        self._init_depotoirs()
        self.pre_collecteurs = {s: PreCollecteurs(self, s) for s in sorted(set(self.d.ilots_secteur))}
        self.agent_pr = {}
        for j, cap in zip(self.plan_pr.retenus, self.d.sites_cap_kg_j[self.plan_pr.retenus]):
            self.agent_pr[int(j)] = PointRegroupement(self, int(j), float(cap), int(self._plus_proche_depotoir(self.d.sites_xy[j])))
        n = len(self.d.ilots_pop)
        self.taux_ab = np.full(n, sc.taux_abonnement)
        self.reduction = np.zeros(n)          # réduction des dépôts sauvages obtenue par la brigade
        self.expire = np.zeros(n)             # jour de fin d'effet
        for i in range(n):
            Ilot(self, i)
        self.brigade, self.mairie = Brigade(self), Mairie(self)
        self.cumul = dict.fromkeys(CUMULS, 0.0)
        self.serie = []
        self._remise_a_zero_jour()

    # --- flotte et coûts ---
    def _init_flotte(self, sc, det):
        """Capacité en plus de celle du plan (camions non mobilisés par les tournées), utilisable pour les dépotoirs."""
        self.capacite_camion_jour_kg = sc.capacite_camion_kg * sc.voyages_max_par_jour
        flotte = len(sc.camions_disponibles()) * self.capacite_camion_jour_kg
        rendement = self.p.rendement_capacite_supplementaire
        self.capacite_supplementaire_kg = max(0.0, flotte - self.capacite_plan_kg) * rendement
        utilises = max(det["plan"]["kpi"]["camions_utilises"], 1)
        self.carburant_par_camion = self.couts_plan["carburant_tournee"] / utilises
        self.personnel_par_camion = self.couts_plan["personnel_tournee"] / utilises

    def acheter_camions(self, n: int, prix: float, stock: float, hausse: float):
        """Décision de la mairie : n camions de plus, utilisables dès le lendemain pour les dépotoirs ; coût d'achat suivi dans le budget."""
        self.capacite_supplementaire_kg += n * self.capacite_camion_jour_kg * self.p.rendement_capacite_supplementaire
        self.camions_achetes += n
        self.investissement_camions += n * prix
        reste = self.p.budget_camions_supplementaires_fcfa - self.investissement_camions
        self.decisions.append({"jour": self.jour, "camions": n, "stock_t": round(stock, 1), "hausse_pct": round(hausse * 100, 1),
                               "investissement_fcfa": round(n * prix), "budget_restant_fcfa": round(reste),
                               "message": f"Jour {self.jour} : le stock de dépotoirs a augmenté de {hausse * 100:.0f} % en {self.p.periode_decision_mairie_jours} jours "
                                          f"({stock:.0f} t) : achat de {n} camion(s), {n * prix / 1e6:.0f} M FCFA ; enveloppe restante {reste / 1e6:.0f} M FCFA."})

    # --- dépotoirs ---
    def distance_eau(self, xy) -> float:
        return float(reseau.profil_geometrique(np.asarray(xy)[None, :], self.commune)["d_eau"][0])

    def _init_depotoirs(self):
        existants = [x for x in acces_depotoirs.lire_tous(graine=self.cfg.simulation.graine) if x.statut != "rejete"]
        self.depotoirs = []
        self.dep_xy = np.empty((0, 2))
        self.proche = np.zeros(len(self.d.ilots_pop), int)
        self.proche_d = np.full(len(self.d.ilots_pop), np.inf)
        if existants:
            xy = reseau.projeter([x.lon for x in existants], [x.lat for x in existants], self.commune)
            for x, pos in zip(existants, xy):
                self._ajouter_depotoir(pos, x.statut, self.p.stock_depotoir_kg)

    def _ajouter_depotoir(self, xy, statut, stock=0.0):
        dep = Depotoir(self, xy, statut, stock)
        dist = np.linalg.norm(self.d.ilots_xy - dep.xy, axis=1)
        dep.voisins = np.flatnonzero(dist <= self.cfg.simulation.brigade_laabal.rayon_action_m)
        mieux = dist < self.proche_d
        self.proche[mieux], self.proche_d[mieux] = len(self.depotoirs), dist[mieux]
        self.depotoirs.append(dep)
        self.dep_xy = np.vstack([self.dep_xy, dep.xy])
        return dep

    def _plus_proche_depotoir(self, xy) -> int:
        if not len(self.dep_xy):
            return -1
        return int(np.argmin(np.linalg.norm(self.dep_xy - xy, axis=1)))

    def deposer_dans_depotoir(self, k: int, kg: float):
        self.fui += kg
        if k >= 0:
            self.depotoirs[k].stock += kg

    def deposer_depuis_ilot(self, idx: int, kg: float):
        """Dépôt sauvage d'un îlot : au dépotoir le plus proche, ou nouveau dépotoir si trop loin."""
        if self.proche_d[idx] > self.p.rayon_apparition_depotoir_m:
            self._ajouter_depotoir(self.d.ilots_xy[idx], "a_confirmer")
        self.deposer_dans_depotoir(int(self.proche[idx]), kg)

    def conversion_abonnements(self, idx):
        """Après sensibilisation, une part des non-abonnés des îlots proches s'abonne."""
        self.taux_ab[idx] += (1 - self.taux_ab[idx]) * self.p.conversion_abonnement_apres_sensibilisation

    def appliquer_effet(self, idx, niveau: int, reduction: float):
        """Effet d'une intervention : on garde la meilleure réduction (pas de cumul entre dépotoirs voisins)."""
        self.reduction[idx] = np.maximum(np.where(self.jour < self.expire[idx], self.reduction[idx], 0.0), reduction)
        self.expire[idx] = self.jour + self.p.duree_effet_jours

    def pression_effective(self, idx: int) -> float:
        return 1.0 - self.reduction[idx] if self.jour < self.expire[idx] else 1.0

    # --- boucle ---
    def _remise_a_zero_jour(self):
        self.produit = self.entre_pr = self.fui = self.collecte_pr = self.collecte_depotoirs = 0.0
        self.caniveau = self.brule = 0.0
        self.recettes_abonnement = self.recettes_amendes = self.amendes_emises_fcfa = 0.0
        self.dep_carburant = self.dep_personnel = self.depenses_brigade = 0.0
        self.nb_sensibilisations = self.nb_sanctions = self.nb_amendes = 0

    def step(self):
        self._remise_a_zero_jour()
        self.agents_by_type[PreCollecteurs].do("step")
        self.agents_by_type[Ilot].shuffle_do("step")
        self.agents_by_type[PointRegroupement].do("step")
        self.mairie.step()
        self.brigade.step()
        for dep in list(self.depotoirs):
            dep.step()
        self.jour += 1
        c = self.couts_plan
        veh, ent, pr_amort = c["vehicules_amortissement_jour"], c["vehicules_entretien_jour"], c["pr_jour"]
        jour = {"produit": self.produit, "collecte": self.collecte_pr + self.collecte_depotoirs, "fui": self.fui,
                "caniveau": self.caniveau, "brule": self.brule, "recettes_abonnement": self.recettes_abonnement,
                "recettes_amendes": self.recettes_amendes, "amendes_emises_fcfa": self.amendes_emises_fcfa,
                "nb_amendes": self.nb_amendes, "dep_carburant": self.dep_carburant, "dep_personnel": self.dep_personnel,
                "dep_vehicules": veh, "dep_entretien": ent, "dep_pr": pr_amort, "dep_brigade": self.depenses_brigade}
        for cle, v in jour.items():
            self.cumul[cle] += v
        cu = self.cumul
        cout_camions = cu["dep_carburant"] + cu["dep_personnel"] + cu["dep_vehicules"] + cu["dep_entretien"] + cu["dep_pr"]
        exploitation = cu["dep_carburant"] + cu["dep_personnel"] + cu["dep_entretien"] + cu["dep_brigade"]
        proches = [d for d in self.depotoirs if d.actif and d.d_eau <= self.p.rayon_risque_inondation_m]
        self.serie.append({
            "jour": self.jour,
            "tonnes_produites": round(self.produit / 1000, 2), "tonnes_collectees": round(jour["collecte"] / 1000, 2),
            "tonnes_enlevees_depotoirs": round(self.collecte_depotoirs / 1000, 2),
            "tonnes_fuite_depotoirs": round(self.fui / 1000, 2),
            "tonnes_caniveau": round(self.caniveau / 1000, 2), "tonnes_brulees": round(self.brule / 1000, 2),
            "taux_couverture": round(self.entre_pr / self.produit, 4) if self.produit else 0.0,
            "depotoirs_actifs": int(sum(bool(d.actif) for d in self.depotoirs)),
            "depotoirs_proches_eau_actifs": len(proches),
            "depotoirs_a_risque_inondation": len(proches) if self.sc.saison_pluies else 0,
            "cout_par_tonne_fcfa": round(cout_camions / (cu["collecte"] / 1000)) if cu["collecte"] else None,
            "depenses_mairie_fcfa": round(cout_camions + cu["dep_brigade"]),
            "depenses_exploitation_fcfa": round(exploitation),
            "investissement_pr_fcfa": round(self.investissement_pr),
            "budget_consomme_fcfa": round(self.investissement_pr + self.investissement_camions + exploitation),
            "recettes_abonnement_fcfa": round(cu["recettes_abonnement"]),
            "recettes_amendes_fcfa": round(cu["recettes_amendes"]),
            "amendes_emises_fcfa": round(cu["amendes_emises_fcfa"]), "nb_amendes": int(cu["nb_amendes"]),
            "stock_depotoirs_tonnes": round(sum(d.stock for d in self.depotoirs) / 1000, 1),
            "sensibilisations": self.nb_sensibilisations, "sanctions": self.nb_sanctions,
            **({"tricycles_en_panne": sum(g.tricycles_en_panne for g in self.pre_collecteurs.values()), "agents_brigade_absents": self.brigade.agents_absents}
               if self.sc.agents_individuels else {}),
            **({"camions_achetes_cumules": self.camions_achetes} if self.sc.mairie_decisionnelle else {}),
        })


def diagnostiquer(m: ModeleOregdo) -> dict:
    """Diagnostic CALCULÉ sur la série : tendance du stock de dépotoirs, flux, camions nécessaires pour le stabiliser."""
    serie, sc, p = m.serie, m.sc, m.p
    n = len(serie)
    stock = np.array([s["stock_depotoirs_tonnes"] for s in serie])
    pente = float(np.polyfit(np.arange(n), stock, 1)[0]) if n >= 2 else 0.0
    fin = serie[-min(10, n):]
    fuite = float(np.mean([s["tonnes_fuite_depotoirs"] for s in fin]))
    enleve = float(np.mean([s["tonnes_enlevees_depotoirs"] for s in fin]))
    tol = p.tolerance_stock_relative * max(fuite, 1e-9)
    tendance = "croissant" if pente > tol else "decroissant" if pente < -tol else "stable"
    cap_sup_j = sc.capacite_camion_kg * sc.voyages_max_par_jour / 1000 * p.rendement_capacite_supplementaire
    deficit = max(pente, 0.0)
    n_sup = math.ceil(deficit / cap_sup_j) if cap_sup_j > 0 else None
    cfg = m.cfg
    fixes = modele_couts.par_camion_jour(cfg)
    cout_camion_j = fixes["personnel"] + fixes["amortissement"] + fixes["entretien"] + m.carburant_par_camion
    d = {
        "tendance_stock": tendance, "stock_initial_tonnes": float(stock[0]), "stock_final_tonnes": float(stock[-1]),
        "variation_stock_t_par_jour": round(pente, 1), "fuite_vers_depotoirs_t_par_jour": round(fuite, 1),
        "tonnes_enlevees_depotoirs_t_par_jour": round(enleve, 1),
        "camions_actuels": len(sc.camions_disponibles()) + m.camions_achetes, "camions_supplementaires_pour_stabiliser": n_sup,
        "camions_necessaires": len(sc.camions_disponibles()) + m.camions_achetes + (n_sup or 0),
        "investissement_camions_supplementaires_fcfa": round(n_sup * cfg.planification.couts.prix_camion_fcfa) if n_sup else 0,
        "budget_annuel_exploitation_supplementaire_fcfa": round(n_sup * cout_camion_j * 365) if n_sup else 0,
        "stable": tendance != "croissant",
    }
    f = lambda x: f"{int(round(x)):,}".replace(",", " ")   # noqa: E731
    if tendance == "croissant":
        d["message"] = (f"Le plan actuel ne suffit pas : le stock de dépotoirs augmente de {pente:.0f} t/jour "
                        f"({d['stock_initial_tonnes']:.0f} t à {d['stock_final_tonnes']:.0f} t en {n} jours ; fuite "
                        f"{fuite:.0f} t/jour contre {enleve:.0f} t/jour enlevées). Il faudrait environ {n_sup} camions "
                        f"supplémentaires ({d['camions_necessaires']} au total), soit {f(d['investissement_camions_supplementaires_fcfa'])} FCFA "
                        f"d'investissement et {f(d['budget_annuel_exploitation_supplementaire_fcfa'])} FCFA/an d'exploitation, "
                        f"ou une baisse durable de la fuite, pour le stabiliser.")
    elif tendance == "stable":
        d["message"] = f"Le stock de dépotoirs est stable ({pente:+.1f} t/jour) : {enleve:.0f} t/jour enlevées pour {fuite:.0f} t/jour de fuite."
    else:
        d["message"] = f"Le stock de dépotoirs diminue de {abs(pente):.0f} t/jour : l'enlèvement ({enleve:.0f} t/j) dépasse la fuite ({fuite:.0f} t/j)."
    d["avertissement"] = ("Plan cible et hypothèses [H] : indicateur de comparaison de scénarios, pas une prévision de la "
                          "situation actuelle de la mairie.")
    return d


def simuler(sc: Scenario, jours: int | None = None, graine: int | None = None, commune: str = COMMUNE_DEFAUT,
            plan: dict | None = None) -> dict:
    """Lance la simulation et renvoie la série temporelle, les indicateurs finaux, les comptes séparés et le diagnostic."""
    sc.valider(commune)
    cfg = charger_config(commune)
    lim = cfg.planification.limites
    n = validation.nombre("jours", jours if jours is not None else cfg.simulation.horizon_jours, 1, lim.jours_simulation_max, entier=True)
    if graine is not None:
        graine = validation.nombre("graine", graine, 0, 2**31 - 1, entier=True)
    debut = time.perf_counter()
    m = ModeleOregdo(sc, graine, commune, plan)
    for _ in range(n):
        m.step()
        if time.perf_counter() - debut > lim.temps_simulation_max_s:   # garde-fou de durée globale
            raise ValueError(f"Simulation interrompue au jour {m.jour} : durée maximale de {lim.temps_simulation_max_s} s dépassée.")
    fin, cu = m.serie[-1], m.cumul
    risque = sum(1 for d in m.depotoirs if d.actif and d.d_eau <= m.p.rayon_risque_inondation_m)
    final = {
        "tonnes_produites_totales": round(cu["produit"] / 1000, 1), "tonnes_collectees_totales": round(cu["collecte"] / 1000, 1),
        "tonnes_fuite_totales": round(cu["fui"] / 1000, 1),
        "tonnes_caniveau_totales": round(cu["caniveau"] / 1000, 1), "tonnes_brulees_totales": round(cu["brule"] / 1000, 1),
        "taux_couverture_moyen": round(float(np.mean([s["taux_couverture"] for s in m.serie])), 4),
        "depotoirs_actifs_fin": fin["depotoirs_actifs"], "cout_par_tonne_fcfa": fin["cout_par_tonne_fcfa"],
        "budget_consomme_fcfa": fin["budget_consomme_fcfa"], "recettes_abonnement_fcfa": fin["recettes_abonnement_fcfa"],
        "recettes_amendes_fcfa": fin["recettes_amendes_fcfa"], "stock_depotoirs_fin_tonnes": fin["stock_depotoirs_tonnes"],
        "depotoirs_a_risque_inondation_saison_pluies": risque,
        "nb_sanctions": int(sum(s["sanctions"] for s in m.serie)), "nb_amendes": int(cu["nb_amendes"]),
    }
    comptes = {   # trois comptes distincts, jamais additionnés
        "mairie": {"investissement_pr_fcfa": round(m.investissement_pr), "investissement_camions_decides_fcfa": round(m.investissement_camions),
                   "carburant_fcfa": round(cu["dep_carburant"]), "personnel_fcfa": round(cu["dep_personnel"]),
                   "vehicules_fcfa": round(cu["dep_vehicules"] + cu["dep_entretien"]),
                   "amortissement_pr_fcfa": round(cu["dep_pr"]), "brigade_fcfa": round(cu["dep_brigade"]),
                   "depenses_totales_fcfa": fin["depenses_mairie_fcfa"], "depenses_exploitation_fcfa": fin["depenses_exploitation_fcfa"]},
        "pre_collecteurs": {"recettes_abonnement_fcfa": fin["recettes_abonnement_fcfa"],
                            "note": "Ces recettes reviennent aux pré-collecteurs et aux GIE, pas à la mairie."},
        "amendes": {"sanctions": final["nb_sanctions"], "amendes_emises": final["nb_amendes"],
                    "montant_emis_fcfa": fin["amendes_emises_fcfa"], "montant_recouvre_fcfa": fin["recettes_amendes_fcfa"],
                    "taux_recouvrement": m.p.taux_recouvrement_amendes,
                    "note": "Sanctions uniquement sur dépotoirs vérifiés ; seule une part des interventions identifie un auteur."},
    }
    return {"nature": "plan_cible", "description": PLAN_CIBLE, "jours": n,
            "graine": cfg.simulation.graine if graine is None else graine, "serie": m.serie, "final": final,
            "comptes": comptes, "diagnostic": diagnostiquer(m), "plan_kpi": m.plan_kpi,
            "options": {"agents_individuels": sc.agents_individuels, "mairie_decisionnelle": sc.mairie_decisionnelle},
            "decisions_mairie": m.decisions}
