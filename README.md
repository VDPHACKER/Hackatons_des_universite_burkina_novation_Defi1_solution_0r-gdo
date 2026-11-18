# Orẽgdo

*Zéro déchet, une ville plus verte.* Équipe **Burkina_Novation**. **Orẽgdo** est le nom du produit ; le paquet Python s'appelle `oregdo`. « Brigade Laabal » désigne la brigade civique d'agents citée par le sujet. Outil libre d'aide à la décision pour l'assainissement d'une commune burkinabè, du **signalement d'un dépotoir sauvage** jusqu'au **plan de gestion** (points de regroupement, tournées de camions), avec une **simulation des acteurs** (ménages, pré-collecteurs, brigade Laabal, mairie). Réalisé pour le Hackathon des Universités 2026, défi « Assainissement de Ouaga ».

> **Données de démonstration.** Les secteurs, les îlots habités, les sites candidats, le CET, le dépôt de camions et tous les signalements de démonstration sont **synthétiques** (étiquetés `synthetique`). Seuls la limite de la commune, l'eau, l'aéroport et les routes principales viennent d'OpenStreetMap. **Google Open Buildings est utilisé** pour la population : 1,27 million de bâtiments répartissent la population RGPH 2019 entre les îlots (modélisé, étiqueté ; contours d'îlots et secteurs restent synthétiques). Les paramètres marqués `[H]` dans `packs/ouaga/commune_config.yaml` sont des hypothèses à confirmer avec la mairie.

## Ce que fait l'outil

| Module | Rôle |
|---|---|
| Vérification | 8 contrôles indépendants, score 0-100, statuts vérifié (≥ 70), à confirmer (40-69), rejeté (< 40), motifs lisibles en français, journal d'audit, rien n'est supprimé |
| Plan de gestion | Points de regroupement (p-médiane sous budget), tournées CVRP (OR-Tools), pluie, pannes, nouveau quartier, recalcul en quelques secondes |
| Simulation | Modèle multi-agents Mesa au pas journalier, brigade Laabal en deux phases (sensibilisation puis sanction), diagnostic honnête du stock de dépotoirs |
| Interface | Une PWA (MapLibre) hors ligne, avec connexion et écrans par rôle : carte, signaler et suivre, points et badges, pré-collecteur, brigade, import d'une collecte, mairie, administration, console du jury, droits et devoirs des ménages |
| Collecte simulée | Campagne de terrain de l'équipe dans un secteur, simulée (à la demande du jury) et comparée à la vérité terrain : `python -m oregdo.verification.collecte_simulee` |
| Bien commun | Export vers OpenStreetMap (GeoJSON et `.osm` JOSM), pack commune réplicable |

## Déploiement en une commande

```powershell
powershell -ExecutionPolicy Bypass -File scripts\deployer.ps1
```
Vérifie Python 3.12, installe tout, crée l'administrateur (mot de passe lisible, affiché une fois) et démarre le serveur sur http://127.0.0.1:8000. Avec Docker : `docker compose up --build` (vérifié). 

### Comptes : le plus simple

Double-cliquer **`scripts\comptes.bat`** : il crée (ou remet à zéro) un compte par rôle et affiche les mots de passe, aussi notés dans `comptes_demo.txt` (hors du dépôt Git).

| Identifiant | Rôle |
|---|---|
| `admin` | administration et jury |
| `mairie` | mairie |
| `brigade` | agent de la brigade Laabal |
| `precollecteur` | pré-collecteur |

`scripts\comptes.bat mon-mot-commun` donne le même mot de passe à tous. Mot de passe perdu ou compte bloqué : `python -m oregdo.comptes reinitialiser --id admin`. L'identifiant ne tient pas compte des majuscules (« Admin » tapé sur un téléphone fonctionne).

## Parcours du jury, écran par écran

Lancez le serveur **quelques minutes avant** la démonstration : le tout premier calcul du plan prend 12 à 30 s, les suivants 1 à 4 s.

1. **Ouvrir** `http://localhost:8000` (ou le port annoncé au lancement). Données fictives signalées par un bandeau jaune permanent.
2. **Créer les comptes** : double-cliquer `scripts\comptes.bat`. Il affiche un mot de passe commun pour `admin`, `mairie`, `brigade` et `precollecteur`.
3. **Habitant (sans compte)** : *Signaler* (photo floutée sur le téléphone, fonctionne sans réseau), *Suivi* avec le code reçu, *Carte* des dépotoirs vérifiés.
4. **Mairie** (bouton *Connexion*, compte `mairie`). La mairie n'a que des outils de décision :

| Onglet | Ce qu'on y voit | Ce qu'on peut y faire |
|---|---|---|
| Tableau de bord | indicateurs, carte, signalements récents ; filtre par arrondissement en haut | repérer les zones mal desservies |
| Plans → Commune | le plan en une phrase, une légende des symboles, les tournées camion par camion, les emplacements conseillés | *Recalculer le plan* |
| Plans → Par arrondissement | les 12 arrondissements classés du moins bien au mieux desservi | feuilles de route imprimables, exports CSV et GeoJSON |
| Simulation → Scénarios | curseurs : **population, abonnement, camions, fréquence de passage, budget, tri** ; acteurs (ménages, pré-collecteurs, brigade, mairie) | *Lancer la simulation*, *Garder ce scénario pour comparer* |
| Plus → Importer une collecte | | charger le **jeu de test caché** (CSV, Excel exporté en CSV, ODK/Kobo, WKT, GeoJSON) |

5. **Épreuve en direct (jury)** (compte `admin`, réservé au jury) : *Simulation → Épreuve en direct*. Un bouton par aléa : panne de camions, saison des pluies, nouveau quartier, **signalements piégés** ; la carte montre l'avant et l'après, avec le temps de recalcul et un journal. *Remettre la situation de référence* annule tout. La mairie n'y a pas accès : elle compare ses propres scénarios.
6. **Brigade Laabal** (compte `brigade`) : *À vérifier* puis *Interventions* (sensibiliser, puis sanctionner en cas de récidive).
7. **Pré-collecteur** (compte `precollecteur`) : *Ma tournée*, et signaler un tas croisé en route.
8. **API** : documentation interactive sur `/docs`. Envoyer directement des pièges : `POST /api/alea/pieges` avec `{"signalements": [...]}` ou `{"generer": 24}` (compte `admin`).

## Installation manuelle (Windows, sans Docker)

Prérequis : Python 3.12.

```powershell
python -m venv .venv
.venv\Scripts\python.exe -m pip install -r requirements.txt
```

Premier import d'OR-Tools ou de GDAL : sous Windows avec *Smart App Control*, il peut échouer une fois (erreur 4551) puis réussir au second essai. Faites ce premier import avant une démonstration.

## Lancer

```powershell
# Premier administrateur : créé au démarrage depuis l'environnement (jamais de mot de passe dans un fichier)
$env:OREGDO_ADMIN_ID = "admin"
$env:OREGDO_ADMIN_MDP = "choisissez-un-mot-de-passe-long"

.venv\Scripts\python.exe -m uvicorn oregdo.app:app --port 8000
```

Ouvrir http://127.0.0.1:8000/ (interface) ou http://127.0.0.1:8000/docs (API interactive). Cette commande n'écoute que l'ordinateur lui-même : **pour un téléphone**, double-cliquer `scripts\lancer_telephone.bat` (HTTPS sur le réseau local) ou voir la documentation livrée séparément. La base est **vide** au départ : les signalements réels arrivent par l'application. Pour une démonstration, l'administrateur charge le jeu synthétique depuis l'écran « Administration » (bouton « Charger la démonstration »), et peut le retirer ensuite sans toucher aux vrais signalements.

### Une application, des écrans par rôle

Une seule application web. Le **citoyen** n'a pas besoin de compte : il signale un tas, reçoit un **code de suivi** et consulte la carte publique des dépotoirs vérifiés. Les autres acteurs se connectent et ne voient que leurs écrans :

| Rôle | Écrans | Exemples d'actions réservées |
|---|---|---|
| Pré-collecteur | ma tournée | saisir ses collectes, voir les passages de camion à son point |
| Brigade Laabal | à vérifier, interventions, importer une collecte | revalider un signalement ; sensibiliser puis sanctionner (loi 022-2005/AN) ; importer un fichier de terrain |
| Mairie | tableau de bord, plan, scénarios, importer une collecte | modifier le scénario, recalculer, simuler, exporter vers OSM, importer un fichier (jeu de test du jury) |
| Administration et jury | comptes, audit, démonstration, console du jury | créer des comptes, injecter des aléas en direct |

Créer d'autres comptes : écran « Administration », ou en ligne de commande, par exemple `python -m oregdo.comptes creer --id awa --nom "Awa Ouédraogo" --role brigade --zone "Secteur 12"`. Il n'y a pas de rôle « enquêteur » : le sujet ne le prévoit pas ; la collecte de terrain passe par l'écran Signaler (tout le monde) et par l'import d'un fichier (brigade, mairie). Mots de passe hachés (scrypt), jetons signés HMAC-SHA256 valables 12 h et révocables, verrouillage après 5 échecs. La clé de signature vient de `OREGDO_SECRET`, sinon elle est générée dans `data/secret.key` (à ne jamais versionner). Aucun HTTPS n'est fourni : à placer derrière un proxy en production. `OREGDO_AUTH=0` ne désactive la vérification que sous pytest.

## Tests

```powershell
.venv\Scripts\python.exe -m pytest tests/verification tests/planning_sim -q
```

Ne lancez pas deux suites en même temps : elles partagent des ressources et peuvent s'échouer mutuellement.

## Fond de carte et graphe routier

`scripts/build_osm_layers.py` lit l'extrait OpenStreetMap local (`scripts/fetch_osm.py`) et produit : le graphe routier réel (`packs/ouaga/graphe_routier.npz`, utilisé pour les distances et les tracés des tournées) et les couches du fond de carte (`web/data/pack/fond/` : routes, quartiers, communes, repères, espaces verts, décharges déjà cartographiées). Environ 80 s. Les noms sur la carte utilisent des polices locales (`web/vendor/fonts/`), donc la carte reste lisible hors ligne.

## Données ouvertes

Le dossier `donnees-ouvertes/` contient les jeux livrés sous licence **ODbL 1.0** (dictionnaire des champs dans `LICENCE-DONNEES.md`) :

| Fichier | Contenu |
|---|---|
| `signalements_synthetiques.geojson` | 300 signalements **fictifs** à Ouagadougou, avec statut et score de vérification |
| `collecte_S33.geojson` | 36 signalements de la collecte de terrain simulée du secteur 33 |
| `verite_terrain_S33.geojson` | les 30 tas réels de cette simulation, pour mesurer la chaîne de vérification |

Aucune donnée personnelle : ni appareil, ni compte, ni photo, ni message vocal.

## Scripts de données et de livrables

| Commande | Ce qu'elle fait |
|---|---|
| `python scripts/build_population_batiments.py` | Répartit la population RGPH entre les îlots d'après les bâtiments Google Open Buildings (`data/raw/open_buildings/`, 871 Mo, téléchargement dans `URL.txt`) |
| `python scripts/exporter_signalements.py` | Écrit le jeu de signalements fictifs en GeoJSON (ODbL) dans `livrables/` |
| `python scripts/scenarios_rapport.py` | Recalcule les scénarios du rapport (`livrables/scenarios_resultats.json`) |
| `python -m oregdo.verification.collecte_simulee [--secteur S12] [--charger]` | Collecte de terrain simulée dans un secteur, comparée à la vérité terrain : `livrables/collecte_simulee/` (bilan, export KoboToolbox, GeoJSON ODbL) |
| `python scripts/construire_icones.py` | Fabrique les icônes de l'application à partir du logo (`web/icons/logo-source.png`) |

## Réutiliser pour une autre commune

Tout seuil et toute donnée locale passent par un **pack commune** : `packs/<commune>/` (couches GeoJSON + `commune_config.yaml`). **Deux packs existent : Ouagadougou et Bobo-Dioulasso**, et le même moteur calcule le plan, les tournées, la simulation et les arrondissements des deux, sans changer son code. Créer le pack d'une nouvelle commune prend deux commandes (`scripts/creer_pack_commune.py` puis `scripts/build_osm_layers.py --commune <code>`) ; lancer la plateforme sur elle : `OREGDO_COMMUNE=<code>`. Voir la documentation livrée séparément.

## Documentation

Ce dépôt contient le **code** et les **scripts de lancement**. La documentation (rapport, rapport technique, matrice de contribution,
diagrammes draw.io, analyses) est livrée séparément par l'équipe Burkina_Novation. Les diagrammes se régénèrent depuis le code :
`python scripts/generer_diagrammes.py` (écrit `docs/modelisation/*.drawio`).

## Limites connues
- Contours d'îlots, secteurs, sites candidats et CET synthétiques. La population par îlot est modélisée d'après les bâtiments Open Buildings (voir la documentation livrée séparément).
- Graphe routier réel (OpenStreetMap) : sens uniques ignorés, revêtement supposé (8 % revêtu), ni vitesses ni trafic ; il occupe 545 Mo de cache dans `data/cache/` (reconstruit automatiquement, ~21 s par saison au premier lancement).
- Le rayon d'accès aux points de regroupement (1 300 m de route) est une hypothèse recalibrée pour rester cohérente avec le recensement de 2019 (voir la documentation livrée séparément).
- La photo n'est pas jugée sur son contenu (classifieur optionnel non fourni) ; l'identifiant d'appareil d'un citoyen n'est pas authentifié.
- Collecte de terrain : simulée (à la demande du jury), pas encore réelle ; `python -m oregdo.verification.collecte_simulee` la reproduit (graine fixe) et compare le résultat à la vérité terrain.
- Non testé : vrai téléphone Android, GPS et caméra réels, installation PWA.
- Import réel dans OpenStreetMap : procédure communautaire requise (consultation, compte dédié) ; l'export refuse les données synthétiques.

## Licences

- **Code** : GNU AGPLv3 (`LICENSE`).
- **Données dérivées d'OpenStreetMap** : ODbL 1.0, © contributeurs OpenStreetMap (attribution obligatoire, partage à l'identique).
- **Données synthétiques** : produites par nos scripts, sans valeur statistique officielle.
- Bibliothèques tierces : voir `requirements.txt` (MapLibre GL JS 4.7.1, BSD-3, copié dans `web/vendor/maplibre/`).
