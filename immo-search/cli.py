#!/usr/bin/env python3
"""Command-line search, and the web server launcher.

    python3 cli.py serve --port 8000
    python3 cli.py search --kind neuf --rooms-min 4 --surface-min 80 \
                          --price-max 425000 --eur-m2-max 5300 \
                          --walk-max-m 450 --mode RER --zone abis,a
    python3 cli.py search --kind ancien --city creteil --rooms-min 4 --format csv
"""

from __future__ import annotations

import argparse
import csv
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from immo.criteria import Criteria, CriteriaError
from immo.engine import Index
from immo.server import serve
from immo.store import load_index

DEFAULT_INDEX = Path(__file__).resolve().parent / "data" / "index.json"

# CLI flag -> query parameter. Kept declarative so the CLI and the HTTP API
# accept exactly the same vocabulary and cannot drift apart.
FLAGS = [
    ("--kind", "kind", "neuf|ancien (répétable)"),
    ("--q", "q", "recherche plein texte"),
    ("--source", "source", "source de données"),
    ("--developer", "developer", "promoteur"),
    ("--dept", "dept", "département, ex. 94"),
    ("--city", "city", "commune"),
    ("--zone", "zone", "zonage ABC: abis, a, b1…"),
    ("--rooms-min", "rooms_min", "nombre de pièces minimum"),
    ("--rooms-max", "rooms_max", "nombre de pièces maximum"),
    ("--surface-min", "surface_min", "surface minimum (m²)"),
    ("--surface-max", "surface_max", "surface maximum (m²)"),
    ("--price-min", "price_min", "prix minimum (€)"),
    ("--price-max", "price_max", "prix maximum (€)"),
    ("--eur-m2-min", "eur_m2_min", "€/m² minimum"),
    ("--eur-m2-max", "eur_m2_max", "€/m² maximum"),
    ("--floor-min", "floor_min", "étage minimum"),
    ("--floor-max", "floor_max", "étage maximum"),
    ("--exposure", "exposure", "exposition: S, SO, E…"),
    ("--delivery-from", "delivery_from", "livraison à partir de, ex. 'T4 2027'"),
    ("--delivery-to", "delivery_to", "livraison jusqu'à, ex. '2029'"),
    ("--sold-after", "sold_after", "vendu après AAAA-MM-JJ"),
    ("--sold-before", "sold_before", "vendu avant AAAA-MM-JJ"),
    ("--walk-max-m", "walk_max_m", "distance à pied max (m, neuf)"),
    ("--walk-max-min", "walk_max_min", "temps de marche max (min, neuf)"),
    ("--crow-max-m", "crow_max_m", "distance à vol d'oiseau max (m)"),
    ("--mode", "mode", "RER|METRO|TRAIN|TRAM"),
    ("--line", "line", "ligne, ex. A, 14, E"),
    ("--fiscal", "fiscal", "PTZ, TVA, BRS, LLI…"),
    ("--feature", "feature", "parking, balcon, terrasse, cave…"),
    ("--kitchen", "kitchen", "separee|cloisonnable|any"),
    ("--only-available", "only_available", "exclure les lots vendus"),
    ("--with-photos", "with_photos", "seulement avec photos"),
    ("--with-plan", "with_plan", "seulement avec plan public"),
    ("--with-exact-address", "with_exact_address", "adresse exacte connue"),
    ("--carrez-only", "carrez_only", "surface Carrez uniquement"),
    ("--keep-unknown", "keep_unknown", "garder les biens sans la donnée filtrée"),
    ("--sort", "sort", "eur_m2|price|surface|rooms|walk|delivery|date"),
    ("--order", "order", "asc|desc"),
    ("--page", "page", "page"),
    ("--per-page", "per_page", "résultats par page"),
]


def add_search_flags(parser: argparse.ArgumentParser) -> None:
    for flag, dest, help_text in FLAGS:
        parser.add_argument(flag, dest=dest, default=None, help=help_text)


def params_from_args(args) -> dict:
    return {
        dest: getattr(args, dest)
        for _, dest, _ in FLAGS
        if getattr(args, dest, None) not in (None, "")
    }


COLUMNS = [
    "kind", "name", "city", "dept", "zone_abc", "rooms", "surface", "price",
    "eur_m2", "delivery_label", "sale_date", "nearest", "walk", "source", "url",
]


def row_for(item: dict) -> dict:
    station = item.get("nearest_station") or {}
    walk = station.get("walk_m")
    crow = station.get("crow_m")
    return {
        "kind": item["kind"],
        "name": (item.get("name") or "")[:44],
        "city": item.get("city") or "",
        "dept": item.get("dept") or "",
        "zone_abc": item.get("zone_abc") or "",
        "rooms": item.get("rooms") or "",
        "surface": item.get("surface") or "",
        "price": item.get("price") or "",
        "eur_m2": item.get("eur_m2") or "",
        "delivery_label": item.get("delivery_label") or "",
        "sale_date": item.get("sale_date") or "",
        "nearest": f"{station.get('name','')} {station.get('mode','')} {station.get('line','')}".strip(),
        "walk": (f"{walk:.0f} m à pied" if walk else (f"~{crow:.0f} m vol d'oiseau" if crow else "")),
        "source": item.get("source") or "",
        "url": item.get("url") or "",
    }


def print_table(rows: list[dict]) -> None:
    if not rows:
        print("aucun résultat")
        return
    head = (
        f"{'TYPE':6s} {'BIEN':46s} {'VILLE':20s} {'ZN':5s} {'P':>2s} "
        f"{'SURF':>7s} {'PRIX':>11s} {'€/M²':>7s} {'LIVR/VENTE':>11s}  TRANSPORT"
    )
    print(head)
    print("-" * len(head))
    for r in rows:
        price = f"{r['price']:,.0f}".replace(",", " ") if r["price"] else "—"
        surface = f"{r['surface']:.1f}" if r["surface"] else "—"
        when = r["delivery_label"] or r["sale_date"] or "—"
        print(
            f"{r['kind']:6s} {r['name']:46s} {r['city'][:18]:20s} "
            f"{r['zone_abc'][:4]:5s} {str(r['rooms']):>2s} {surface:>7s} "
            f"{price:>11s} {str(r['eur_m2'] or '—'):>7s} {when:>11s}  "
            f"{r['nearest'][:26]:28s} {r['walk']}"
        )


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--index", default=str(DEFAULT_INDEX))
    sub = parser.add_subparsers(dest="command", required=True)

    p_search = sub.add_parser("search", help="rechercher en ligne de commande")
    add_search_flags(p_search)
    p_search.add_argument("--format", choices=["table", "csv", "json"], default="table")

    p_serve = sub.add_parser("serve", help="lancer l'interface web")
    p_serve.add_argument("--host", default="127.0.0.1")
    p_serve.add_argument("--port", type=int, default=8000)

    sub.add_parser("stats", help="résumé de l'index")

    args = parser.parse_args()
    listings, meta = load_index(Path(args.index))
    index = Index(listings)

    if args.command == "serve":
        serve(index, meta, host=args.host, port=args.port)
        return

    if args.command == "stats":
        print(json.dumps({**meta, **Index.stats(listings),
                          "count": len(listings)}, indent=2, ensure_ascii=False, default=str))
        return

    try:
        criteria = Criteria.from_params(params_from_args(args))
    except CriteriaError as exc:
        sys.exit(f"critère invalide — {exc}")

    result = index.search(criteria, with_facets=False)
    rows = [row_for(item) for item in result["results"]]

    if args.format == "json":
        print(json.dumps(result, ensure_ascii=False, indent=1, default=str))
        return
    if args.format == "csv":
        writer = csv.DictWriter(sys.stdout, fieldnames=COLUMNS)
        writer.writeheader()
        writer.writerows(rows)
        return

    print_table(rows)
    stats = result["stats"]
    eur = stats.get("eur_m2")
    print(
        f"\n{result['total']} résultat(s) — page {result['page']}/{result['pages']}"
        + (f" · €/m² médian {eur['median']:.0f} (min {eur['min']:.0f}, max {eur['max']:.0f})"
           if eur else "")
    )


if __name__ == "__main__":
    main()
