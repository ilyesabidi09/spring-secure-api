# VEFA Île-de-France — recherche T4 près d'un RER

Pipeline de collecte et de filtrage de programmes immobiliers neufs (VEFA) en
Île-de-France, à partir des **pages de listing publiques** de neuf agrégateurs et
sites promoteurs.

## Critères de recherche

| Critère | Valeur |
|---|---|
| Typologie | T4 |
| Surface | ≥ 80 m² |
| Prix (bien seul) | ≤ 425 000 € |
| €/m² | ≤ 5 300 |
| Distance gare RER | ≤ 450 m **à pied** (réseau piéton réel) |
| Livraison | T4 2027 → 2029 |
| Zonage | A bis / A |
| PTZ | éligible |

## Exécution

```bash
python3 run.py                      # tout le pipeline
python3 run.py --only explorimmoneuf bouygues
python3 run.py --skip-scrape        # re-filtrer sans recrawler
python3 run.py --delay 2.0          # ralentir le crawl
```

Sorties dans `out/` :

* `vefa_idf_full.csv` — tous les programmes collectés, avec le verdict par
  critère (`ok_*` = `oui` / `non` / `?`) et les colonnes `fails` / `unknown`.
* `vefa_idf_retenus.csv` — uniquement les programmes qui passent **tous** les
  critères.
* `scrape_report.json` — volumétrie et exclusions par source.

Le tri est fait par €/m² croissant ; les programmes dont le €/m² n'est pas
calculable (surface non publiée) sont rejetés en fin de fichier.

## Déontologie du crawl

* **robots.txt appliqué sur chaque requête** (`vefa/robots.py`), avec le
  matching REP complet (`*`, `$`, Allow le plus spécifique l'emporte). Si le
  fichier ne peut pas être lu, l'hôte n'est pas crawlé (*fail closed*).
* Conséquences concrètes, respectées par le code :
  * `explorimmoneuf` et `vinci` interdisent toute URL avec query string ;
  * `bouygues` interdit **tous** les PDF et `/ajax/get_program_lots/` (le détail
    des lots n'est donc pas collecté chez eux) ;
  * `sogeprom` interdit les plaquettes PDF ;
  * `explorimmoneuf` interdit `/rest/` (API interne des lots).
* Un seul hit par hôte toutes les `--delay` secondes, et cache disque
  (`.cache/http`) : un re-run ne recoûte rien aux sites.
* **Aucune donnée n'est envoyée** : pas de formulaire, pas de compte, pas de
  demande de brochure. Le pipeline lit uniquement des pages publiques.

## Données de référence

| Donnée | Source | Clé requise |
|---|---|---|
| Zonage ABC (A bis / A / B1…) | `data.iledefrance.fr` (Région ÎdF) | non |
| Gares RER + coordonnées | `data.iledefrance-mobilites.fr` (IDFM) | non |
| Géocodage d'adresses | `api-adresse.data.gouv.fr` (BAN) | non |
| Distance piétonne | `valhalla1.openstreetmap.de`, profil `pedestrian` | non |

**Pourquoi Valhalla et pas OSRM :** le serveur de démonstration OSRM public n'a
que le profil voiture chargé et répond à `/route/v1/foot/` par un itinéraire
routier (2 110 m en 405 s ≈ 18 km/h, ce qui n'est pas une allure de marche). Le
critère « 400 m réels à pied » exige un vrai routage piéton.

Le routage piéton n'est calculé que pour les programmes dont une gare est déjà à
moins de 450 m à vol d'oiseau : un trajet à pied ne peut pas être plus court que
la ligne droite, donc les autres sont éliminés sans appel réseau.

## Limite structurelle des sources

Les surfaces et les prix **par typologie** sont la donnée que ces sites monnaient
contre un formulaire de contact. Concrètement :

| Source | Prix T4 | Surface T4 |
|---|---|---|
| explorimmoneuf | oui (`accommodations[roomCount=4]`) | partiel |
| coteneuf | partiel (souvent masqué en `XXX €`) | partiel |
| bouygues, vinci, nexity, K&B, sogeprom, tulnc, diagonale | non — seulement « à partir de » au niveau programme | non |

Le CSV distingue donc `price_t4_min` (prix réellement attribuable au T4) de
`price_program_min` (prix d'appel du programme, souvent un studio). Le €/m²
n'est calculé que sur des couples prix/surface tous deux attribuables au T4 —
jamais en mélangeant un prix d'appel avec une surface maximale, ce qui
fabriquerait un €/m² faux et flatteur.
