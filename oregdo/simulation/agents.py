"""Agents de la simulation (Mesa) : ménages/îlots, pré-collecteurs, points de regroupement, dépotoirs, brigade, mairie.

Les agents ne contiennent que leur logique ; l'état agrégé (tonnages du jour, recettes) est tenu par le modèle.
"""
import mesa
import numpy as np

from ..planning import valorisation


class Tricycle(mesa.Agent):
    """Un tricycle de pré-collecte (option « agents_individuels ») : capacité propre, pannes aléatoires de quelques jours."""

    def __init__(self, model, secteur: str, capacite_kg: float):
        super().__init__(model)
        self.secteur = secteur
        ecart = max(0.2, 1 + model.rng.normal(0, model.p.heterogeneite_tricycle))     # un tricycle n'est jamais identique à un autre
        self.capacite_jour = capacite_kg * model.p.voyages_pre_collecteur_par_jour * ecart
        self.panne_jusqua = -1

    @property
    def en_panne(self) -> bool:
        return self.model.jour < self.panne_jusqua

    def step(self):
        m = self.model
        if not self.en_panne and m.rng.random() < m.p.panne_tricycle_prob_jour:
            self.panne_jusqua = m.jour + m.p.panne_tricycle_duree_jours

    def capacite_effective(self) -> float:
        return 0.0 if self.en_panne else self.capacite_jour


class PreCollecteurs(mesa.Agent):
    """Pré-collecteurs (tricycles) d'un secteur : capacité journalière commune, ou somme de tricycles individuels (option du scénario)."""

    def __init__(self, model, secteur: str):
        super().__init__(model)
        p = model.cfg.simulation.pre_collecteurs
        self.secteur = secteur
        self.tricycles = []
        if model.sc.agents_individuels:
            self.tricycles = [Tricycle(model, secteur, p.capacite_kg) for _ in range(max(1, int(round(p.nombre_par_secteur))))]
            self.capacite_jour = sum(t.capacite_jour for t in self.tricycles)
        else:
            self.capacite_jour = p.nombre_par_secteur * p.capacite_kg * model.p.voyages_pre_collecteur_par_jour
        self.reste = self.capacite_jour

    def prendre(self, kg: float) -> float:
        """Collecte jusqu'à la capacité restante ; renvoie les kg réellement pris."""
        pris = min(kg, self.reste)
        self.reste -= pris
        return pris

    @property
    def tricycles_en_panne(self) -> int:
        return sum(t.en_panne for t in self.tricycles)

    def step(self):
        if self.tricycles:                      # chaque tricycle vit sa journée (panne ou non) ; la capacité du jour est leur somme
            for t in self.tricycles:
                t.step()
            self.capacite_jour = sum(t.capacite_effective() for t in self.tricycles)
        self.reste = self.capacite_jour


class PointRegroupement(mesa.Agent):
    """PR retenu par le plan : stock qui se remplit (pré-collecteurs, apport volontaire) et se vide (camions)."""

    def __init__(self, model, site: int, capacite_kg_j: float, depotoir_voisin: int):
        super().__init__(model)
        self.site, self.stock, self.depotoir_voisin = site, 0.0, depotoir_voisin
        self.stock_max = capacite_kg_j * model.p.stock_max_jours_pr

    def step(self):
        """Un PR plein déborde : l'excédent part vers le dépotoir voisin (fuite)."""
        if self.stock > self.stock_max:
            exces = self.stock - self.stock_max
            self.stock = self.stock_max
            self.model.deposer_dans_depotoir(self.depotoir_voisin, exces)


class Depotoir(mesa.Agent):
    """Dépotoir sauvage : stock, statut de vérification et état de l'intervention de la brigade."""

    def __init__(self, model, xy, statut: str, stock: float = 0.0):
        super().__init__(model)
        self.xy, self.statut, self.stock = np.asarray(xy, float), statut, float(stock)
        self.jour_creation = model.jour
        self.etat = 0                  # 0 rien, 1 sensibilisé, 2 sanctionné
        self.jour_derniere_action = -10**6
        self.nb_sanctions = 0
        self.voisins = np.array([], int)   # îlots à portée d'action de la brigade
        self.d_eau = float(model.distance_eau(self.xy))

    @property
    def a_risque_inondation(self) -> bool:
        """Actif et proche d'un plan d'eau : risque en saison des pluies."""
        return self.actif and self.d_eau <= self.model.p.rayon_risque_inondation_m

    @property
    def actif(self) -> bool:
        return self.stock > self.model.p.seuil_depotoir_actif_kg

    def step(self):
        """Un dépotoir apparu sur signalement devient « vérifié » après le délai de vérification."""
        if self.statut == "a_confirmer" and self.model.jour - self.jour_creation >= self.model.p.delai_verification_jours:
            self.statut = "verifie"


class Ilot(mesa.Agent):
    """Les ménages d'un îlot : produisent, s'abonnent (ou non), apportent au PR ou jettent au dépotoir."""

    def __init__(self, model, idx: int):
        super().__init__(model)
        d = model.d
        self.idx, self.secteur = idx, d.ilots_secteur[idx]
        self.population = d.ilots_pop[idx] * model.sc.facteur_population
        self.menages = self.population * model.cfg.demographie.menages / model.cfg.demographie.population
        pr = model.plan_pr.affectation[idx]
        self.pr = model.agent_pr.get(int(pr)) if pr >= 0 else None
        p = model.cfg.simulation.pre_collecteurs
        self.tarif = p.tarif_abonnement_fcfa if d.ilots_type[idx] == "loti" else model.p.tarif_quartier_populaire_fcfa

    def step(self):
        m = self.model
        prod = self.population * m.cfg.demographie.production_kg_hab_jour * valorisation.facteur_collecte(m.sc, m.commune) * \
            max(0.0, 1 + m.rng.normal(0, m.p.variabilite_production))
        taux = m.taux_ab[self.idx]
        abonnes = prod * taux
        livre = 0.0
        if self.pr is not None:
            pris = m.pre_collecteurs[self.secteur].prendre(abonnes)
            apport = (prod - abonnes) * m.p.apport_volontaire_non_abonnes
            livre = pris + apport
            self.pr.stock += livre
            if abonnes > 0:   # on ne facture que ce qui est réellement collecté
                m.recettes_abonnement += self.menages * taux * self.tarif / m.jours_par_mois * pris / abonnes
        reste = prod - livre
        pression = m.pression_effective(self.idx)
        fuite = reste * m.cfg.simulation.fuite_vers_depotoir_si_pr_inaccessible * pression   # dépôt sauvage (tas, rue)
        caniveau = reste * m.part_caniveau * pression                                          # fossé / caniveau (RGPH)
        m.produit += prod
        m.entre_pr += livre
        m.caniveau += caniveau
        m.brule += max(reste - fuite - caniveau, 0.0)   # brûlé / enfoui / fosse fumière : non simulé finement
        if fuite > 0:
            m.deposer_depuis_ilot(self.idx, fuite)


class AgentBrigade(mesa.Agent):
    """Un agent de la brigade (option « agents_individuels ») : accumule ses interventions et peut être absent quelques jours."""

    def __init__(self, model):
        super().__init__(model)
        self.reserve, self.absent_jusqua = 0.0, -1

    @property
    def absent(self) -> bool:
        return self.model.jour < self.absent_jusqua

    def interventions_du_jour(self) -> int:
        m = self.model
        if not self.absent and m.rng.random() < m.p.absence_agent_brigade_prob_jour:
            self.absent_jusqua = m.jour + m.p.absence_agent_brigade_duree_jours
        if self.absent:
            return 0
        self.reserve += m.p.interventions_par_agent_jour
        n = int(self.reserve)
        self.reserve -= n
        return n


class Brigade(mesa.Agent):
    """Brigade Laabal en deux phases : sensibilisation à la première intervention, sanction à la récidive.
    Par défaut un budget commun d'interventions ; avec l'option du scénario, chaque agent de la brigade est un agent avec ses absences."""

    def __init__(self, model):
        super().__init__(model)
        self.agents = [AgentBrigade(model) for _ in range(int(model.cfg.simulation.brigade_laabal.effectif))] if model.sc.agents_individuels else []

    @property
    def agents_absents(self) -> int:
        return sum(a.absent for a in self.agents)

    def step(self):
        m, c = self.model, self.model.cfg.simulation.brigade_laabal
        budget = sum(a.interventions_du_jour() for a in self.agents) if self.agents else int(c.effectif * m.p.interventions_par_agent_jour)
        m.depenses_brigade += c.effectif * m.p.cout_agent_brigade_jour_fcfa
        cibles = sorted((d for d in m.depotoirs if d.actif), key=lambda d: -d.stock)
        for dep in cibles:
            if budget <= 0:
                break
            if dep.etat == 0:
                m.appliquer_effet(dep.voisins, 1, m.p.reduction_sensibilisation)
                dep.etat, dep.jour_derniere_action = 1, m.jour
                m.nb_sensibilisations += 1
                m.conversion_abonnements(dep.voisins)
                budget -= 1
            elif dep.statut == "verifie" and m.jour - dep.jour_derniere_action >= c.phase_sensibilisation_jours:
                # Récidive sur un dépotoir VÉRIFIÉ (jamais sur un signalement non vérifié : risque de sanction injuste).
                # Un dépôt anonyme ne peut pas être verbalisé : seule une part des interventions identifie un auteur.
                identifies = int(np.sum(m.rng.random(int(m.p.contrevenants_par_intervention)) < m.p.part_depots_auteur_identifiable))
                for _ in range(identifies):
                    amende = int(m.rng.integers(c.amende_fcfa[0], c.amende_fcfa[1] + 1)) * (2 if dep.nb_sanctions >= 1 else 1)
                    m.amendes_emises_fcfa += amende
                    m.nb_amendes += 1
                    m.recettes_amendes += amende * m.p.taux_recouvrement_amendes
                m.appliquer_effet(dep.voisins, 2, m.p.reduction_sanction)
                dep.etat, dep.jour_derniere_action = 2, m.jour
                dep.nb_sanctions += 1
                m.nb_sanctions += 1
                budget -= 1


class Mairie(mesa.Agent):
    """Mairie et flotte : capacité quotidienne issue du plan (pannes, pluies, distances déjà prises en compte).
    Avec l'option « mairie_decisionnelle », elle observe aussi le stock de dépotoirs et décide d'acheter des camions."""

    def decider(self):
        """Tous les N jours : si le stock de dépotoirs a augmenté de plus que le seuil, acheter des camions dans la limite du budget.
        Chaque décision est enregistrée avec ses raisons (la mairie n'agit pas à l'aveugle et ne dépasse jamais l'enveloppe)."""
        m, p = self.model, self.model.p
        if m.jour == 0 or m.jour % p.periode_decision_mairie_jours:
            return
        stock = sum(d.stock for d in m.depotoirs) / 1000
        avant, m.stock_dernier_examen = m.stock_dernier_examen, stock
        if avant is None or avant <= 0:
            return
        hausse = (stock - avant) / avant
        if hausse <= p.seuil_hausse_stock_decision:
            return
        prix = m.cfg.planification.couts.prix_camion_fcfa
        n = min(int(p.camions_par_decision), int((p.budget_camions_supplementaires_fcfa - m.investissement_camions) // prix))
        if n <= 0:
            m.decisions.append({"jour": m.jour, "camions": 0, "stock_t": round(stock, 1), "hausse_pct": round(hausse * 100, 1),
                                "message": f"Jour {m.jour} : le stock de dépotoirs augmente de {hausse * 100:.0f} % mais l'enveloppe de camions est épuisée."})
            return
        m.acheter_camions(n, prix, stock, hausse)

    def step(self):
        m = self.model
        if m.sc.mairie_decisionnelle:
            self.decider()
        if m.jour % m.sc.frequence_collecte_jours != 0 or m.capacite_plan_kg <= 0:
            return
        # Deux enveloppes issues du plan : dépotoirs vérifiés (prioritaires, plafonnés au tonnage planifié),
        # puis PR les plus remplis avec le reste de la capacité. Un stock de dépotoir géant ne peut donc pas
        # affamer les PR au-delà de ce que le plan a prévu.
        reste_dep = m.capacite_depotoirs_kg + m.capacite_supplementaire_kg
        for dep in sorted((d for d in m.depotoirs if d.statut == "verifie"), key=lambda d: -d.stock):
            pris = min(dep.stock, reste_dep)
            dep.stock -= pris
            reste_dep -= pris
            m.collecte_depotoirs += pris
        reste = m.capacite_plan_kg - m.capacite_depotoirs_kg
        for pr in sorted(m.agent_pr.values(), key=lambda a: -a.stock):
            pris = min(pr.stock, reste)
            pr.stock -= pris
            reste -= pris
            m.collecte_pr += pris
        # Utilisation : la part du plan réellement chargée, plus les camions supplémentaires mobilisés pour les dépotoirs.
        sup_utilise = max(0.0, m.collecte_depotoirs - m.capacite_depotoirs_kg)
        utilise = m.collecte_pr + m.collecte_depotoirs
        taux_plan = min(1.0, (m.collecte_pr + min(m.collecte_depotoirs, m.capacite_depotoirs_kg)) / m.capacite_plan_kg)
        extra_camions = sup_utilise / m.capacite_camion_jour_kg if m.capacite_camion_jour_kg else 0.0
        c = m.couts_plan
        m.dep_carburant += c["carburant_tournee"] * taux_plan + m.carburant_par_camion * extra_camions
        m.dep_personnel += c["personnel_tournee"] * (1 if utilise > 0 else 0) + m.personnel_par_camion * extra_camions
