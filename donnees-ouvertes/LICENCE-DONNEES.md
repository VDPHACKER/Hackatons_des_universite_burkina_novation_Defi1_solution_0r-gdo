# Jeu de signalements — licence et dictionnaire

**Fichier :** `signalements_synthetiques.geojson` (300 points, Ouagadougou).
**Licence :** Open Database License (ODbL) 1.0 — https://opendatacommons.org/licenses/odbl/1-0/
Vous pouvez copier, adapter et réutiliser ces données, y compris commercialement, à condition de citer la source
(*Orẽgdo, Hackathon des Universités 2026*) et de repartager les bases dérivées sous la même licence.
L'ODbL est la licence d'OpenStreetMap : ce jeu peut donc rejoindre une base OSM sans conflit de licence.

> **Ces signalements sont FICTIFS.** Ils servent à démontrer l'outil (consigne de l'organisateur). Ne pas les prendre pour des
> observations de terrain. Chaque point porte `synthetique: true`. Régénération : `python scripts/exporter_signalements.py`.

## Champs

| Champ | Sens |
|---|---|
| `id` | Identifiant du fichier (S0001…), sans lien avec la base interne |
| `date` | Date du signalement (AAAA-MM-JJ) |
| `taille` | `petit` · `moyen` · `grand` · `tres_grand` |
| `nature` | Nature des déchets (ménagers, plastiques, gravats, végétaux, dangereux) |
| `caniveau` | `true` si le tas bouche un caniveau |
| `accessibilite` | Accès d'un véhicule : `camion` · `tricycle` · `difficile` |
| `statut` | Résultat de la vérification : `verifie` · `a_confirmer` · `rejete` (un rejet n'est jamais supprimé) |
| `score` | Score de confiance de 0 à 100 (≥ 70 = vérifié, 40 à 69 = à confirmer, < 40 = rejeté) |
| `nb_photos` | Nombre de photos reçues (les photos ne sont pas conservées) |
| `source` | `application` · `csv` · `geojson` |
| `secteur` | Secteur déclaré (découpage synthétique) |
| `synthetique` | Toujours `true` dans ce fichier |

## Ce qui n'est pas dans le fichier
Aucune donnée personnelle : ni enquêteur, ni identifiant d'appareil, ni compte, ni code de suivi, ni message vocal, ni photo.
