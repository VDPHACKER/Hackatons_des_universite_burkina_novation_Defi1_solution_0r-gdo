"""Scénario : paramètres modifiables par l'utilisateur ou par le jury."""
from dataclasses import asdict, dataclass, field, replace

from ..config import COMMUNE_DEFAUT, charger_config
from . import validation


@dataclass
class Scenario:
    facteur_population: float = 1.0        # 1.0 = RGPH 2019 ; 1.6 ~ 4 M d'habitants
    taux_abonnement: float = 0.437
    taux_tri: float = 0.0                  # part des ménages qui trient et revendent leurs recyclables (valorisation, hypothèses [H])
    camions_nombre: int = 20
    camions_en_panne: list = field(default_factory=list)   # indices de camions (0..nombre-1)
    capacite_camion_kg: int = 7000
    voyages_max_par_jour: int = 3
    frequence_collecte_jours: int = 1
    budget_pr_fcfa: float = 60_000_000
    rayon_acces_pr_m: float = 600
    saison_pluies: bool = False
    nouveaux_quartiers: list = field(default_factory=list)  # {nom, population, polygone (GeoJSON)}
    signalements_pieges_recus: int = 0     # compteur d'audit : n'influence pas le plan
    # Options de la SIMULATION seulement (le plan n'en dépend pas ; désactivées par défaut : les résultats du rapport sont inchangés).
    agents_individuels: bool = False       # les tricycles sont des agents (capacité propre, pannes) au lieu d'un groupe par secteur
    mairie_decisionnelle: bool = False     # la mairie observe le stock de dépotoirs et décide d'acheter des camions, dans la limite d'un budget

    @classmethod
    def depuis_config(cls, commune: str = COMMUNE_DEFAUT) -> "Scenario":
        c = charger_config(commune)
        p = c.planification
        return cls(
            taux_abonnement=c.demographie.taux_abonnement,
            camions_nombre=p.camions.nombre,
            capacite_camion_kg=p.camions.capacite_kg,
            voyages_max_par_jour=p.camions.voyages_max_par_jour,
            frequence_collecte_jours=p.frequence_collecte_jours,
            budget_pr_fcfa=p.budget_pr_fcfa,
            rayon_acces_pr_m=p.rayon_acces_pr_m,
        )

    def modifie(self, **champs) -> "Scenario":
        """Copie avec modifications ; refuse les champs inconnus."""
        inconnus = set(champs) - set(self.__dataclass_fields__)
        if inconnus:
            raise ValueError(f"Paramètres inconnus : {', '.join(sorted(inconnus))}")
        return replace(self, **champs)

    def valider(self, commune: str = COMMUNE_DEFAUT) -> None:
        """Vérifie types et bornes (planification.limites) ; normalise les nombres entiers. ValueError en français."""
        lim = validation.limites(commune)
        n = validation.nombre
        self.camions_nombre = n("camions_nombre", self.camions_nombre, *lim.camions_nombre, entier=True)
        self.facteur_population = n("facteur_population", self.facteur_population, *lim.facteur_population)
        self.taux_abonnement = n("taux_abonnement", self.taux_abonnement, *lim.taux_abonnement)
        self.taux_tri = n("taux_tri", self.taux_tri, *lim.taux_tri)
        self.budget_pr_fcfa = n("budget_pr_fcfa", self.budget_pr_fcfa, *lim.budget_pr_fcfa)
        self.rayon_acces_pr_m = n("rayon_acces_pr_m", self.rayon_acces_pr_m, *lim.rayon_acces_pr_m)
        self.frequence_collecte_jours = n("frequence_collecte_jours", self.frequence_collecte_jours, *lim.frequence_collecte_jours, entier=True)
        self.voyages_max_par_jour = n("voyages_max_par_jour", self.voyages_max_par_jour, *lim.voyages_max_par_jour, entier=True)
        self.capacite_camion_kg = n("capacite_camion_kg", self.capacite_camion_kg, *lim.capacite_camion_kg, entier=True)
        self.signalements_pieges_recus = n("signalements_pieges_recus", self.signalements_pieges_recus, 0, None, entier=True)
        for nom in ("saison_pluies", "agents_individuels", "mairie_decisionnelle"):
            if not isinstance(getattr(self, nom), bool):
                raise ValueError(f"« {nom} » doit valoir vrai ou faux.")
        if not isinstance(self.camions_en_panne, list):
            raise ValueError("« camions_en_panne » doit être une liste d'identifiants de camions.")
        pannes = [n("identifiant de camion en panne", i, 0, self.camions_nombre - 1, entier=True) for i in self.camions_en_panne]
        if len(set(pannes)) != len(pannes):
            raise ValueError("« camions_en_panne » contient des doublons.")
        self.camions_en_panne = pannes
        if not isinstance(self.nouveaux_quartiers, list) or len(self.nouveaux_quartiers) > lim.nouveaux_quartiers_max:
            raise ValueError(f"« nouveaux_quartiers » : liste de {lim.nouveaux_quartiers_max} quartiers au plus.")
        self.nouveaux_quartiers = [validation.valider_quartier(q, i, commune)[0] for i, q in enumerate(self.nouveaux_quartiers)]

    def camions_disponibles(self) -> list:
        panne = {int(i) for i in self.camions_en_panne}
        return [i for i in range(self.camions_nombre) if i not in panne]

    def to_dict(self) -> dict:
        return asdict(self)
