# Immo Search — moteur de recherche immobilier Île-de-France

Recherche multicritère sur deux jeux de données volontairement séparés :

| | **Neuf en vente** | **Ancien vendu** |
|---|---|---|
| Nature | programmes VEFA commercialisés | ventes réellement enregistrées |
| Prix | prix **demandé** aujourd'hui | prix **payé**, avec quelques mois de décalage |
| Source | pages de listing publiques (9 sites) | DVF (`files.data.gouv.fr/geo-dvf`) |
| Sert à | trouver un bien | vérifier un prix |

Les deux ne sont jamais mélangés dans une moyenne : comparer un prix affiché à
un autre prix affiché ne dit rien du marché.

> **Il n'existe pas de flux légal d'annonces « ancien » en vente.** SeLoger
> l'interdit dans son robots.txt ; PAP, Bien'ici et LeBonCoin répondent 403 à
> tout client non-navigateur. L'ancien est donc représenté par les transactions
> DVF, qui sont une meilleure référence de prix qu'une annonce de toute façon.

## Démarrage

`data/` n'est pas versionné (l'index pèse des centaines de Mo et se
reconstruit). **Il faut donc le bâtir une fois avant de lancer le serveur :**

```bash
cd immo-search

# 1. Construire l'index. Une fois suffit ; il est réutilisé ensuite.
python3 build_index.py --dvf-depts 94 93 --dvf-years 2024   # léger, ~40 s
python3 cli.py serve                                        # http://127.0.0.1:8000
```

Le volet « neuf » est repris de `../vefa-idf/out/vefa_idf_full.csv`, produit par
le pipeline voisin. Sans ce fichier l'index ne contient que des ventes DVF, et
`build_index.py` l'annonce (`0 programmes`) au lieu d'échouer.

Coût selon l'étendue demandée, mesuré sur cette machine :

| Étendue | Index | Démarrage | RAM |
|---|---|---|---|
| 1 département, 1 année | ~14 Mo | ~2 s | ~150 Mo |
| 8 départements, 2 années | ~278 Mo | ~25 s | ~1,2 Go |

Le serveur charge tout en mémoire au démarrage : sur l'index complet il ne
répond qu'au bout d'une vingtaine de secondes. Les recherches sont ensuite
instantanées (~120 ms, ~260 ms avec les facettes). Commencez petit.

```bash
python3 -m unittest discover -s tests     # 61 tests
```

Aucune dépendance : bibliothèque standard uniquement, serveur compris.

## Recherche en ligne de commande

```bash
python3 cli.py search --kind neuf --rooms-min 4 --surface-min 80 \
    --price-max 425000 --eur-m2-max 5300 --walk-max-m 450 --mode RER \
    --zone abis,a --delivery-from "T4 2027" --delivery-to 2029

python3 cli.py search --kind ancien --city creteil --rooms-min 4 \
    --surface-min 80 --sort eur_m2 --format csv > comparables.csv
```

Le CLI et l'API HTTP partagent exactement le même vocabulaire de critères : une
recherche testée en ligne de commande se rejoue à l'identique dans l'interface.

## Filtres

**Bien** — type (neuf/ancien), plein texte, pièces, surface, prix, €/m², étage,
exposition, promoteur, source.
**Lieu** — département, commune, zonage ABC (A bis / A / B1 / B2).
**Transport** — mode (RER, métro, Transilien, tram), ligne, distance à pied,
distance à vol d'oiseau.
**Temps** — fenêtre de livraison (neuf), fenêtre de date de vente (ancien).
**Qualifiants** — dispositifs (PTZ, TVA réduite, BRS, LLI, LMNP, Jeanbrun),
équipements (parking, balcon, terrasse, jardin, cave, ascenseur), cuisine
séparée ou cloisonnable (TMA), lots disponibles.
**Qualité de la donnée** — adresse exacte connue, avec photos, avec plan public,
surface Carrez uniquement.

## Trois décisions qui évitent des chiffres faux

**Distance à pied vs vol d'oiseau.** Le trajet piéton réel (Valhalla, profil
`pedestrian`) n'est calculé que pour les programmes neufs. Router 100 000 ventes
DVF via une API publique prendrait des jours, et personne ne choisit un
comparable au temps de marche. Les deux filtres sont donc distincts et étiquetés
comme tels — jamais l'un présenté comme l'autre. Le serveur de démonstration
OSRM est inutilisable ici : il n'a que le profil voiture chargé et répond à
`/route/v1/foot/` par un itinéraire routier.

**Mutations atypiques.** DVF enregistre tout transfert : nue-propriété, vente
entre proches, part indivise. Leur €/m² est hors marché et, en tri croissant,
ils occupent toute la première page. Ils sont donc écartés par défaut — d'abord
par des bornes absolues, puis par comparaison à la **médiane de leur propre
commune** (un plancher fixe ne peut pas servir Paris et la Seine-et-Marne à la
fois). La case « Inclure les mutations atypiques » les fait réapparaître,
signalés et motivés.

**Donnée absente ≠ critère non rempli.** Un bien qui ne publie pas sa surface
n'est pas un bien « de moins de 80 m² ». Par défaut il est écarté du résultat ;
la case « Garder les biens sans la donnée filtrée » les conserve, marqués « ? ».
Le €/m² n'est jamais calculé en croisant un prix d'appel avec une surface issue
d'un autre lot.

## Architecture

```
immo/model.py      Listing unifié, plausibilité des prix
immo/criteria.py   critères typés + validation + prédicat de correspondance
immo/engine.py     filtrage, tri, pagination, facettes, comparables
immo/ingest.py     lecture VEFA + téléchargement/normalisation DVF
immo/geo.py        zonage, gares tous modes, géocodage BAN, marche Valhalla
immo/server.py     serveur HTTP + routage API (stdlib)
immo/web/          interface (aucun framework, aucun build)
```

Les facettes sont calculées en neutralisant leur propre filtre : le compteur
affiché à côté de « Val-de-Marne » est exactement le nombre de résultats obtenus
en cliquant dessus. Un test le vérifie pour chaque valeur de facette.

L'état de la recherche vit dans l'URL : toute recherche est un lien partageable.
