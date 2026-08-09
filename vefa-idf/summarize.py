#!/usr/bin/env python3
"""Read out/vefa_idf_full.csv and print the shortlist plus the near-misses.

The brief is arithmetically tight: 80 m² at 5 300 €/m² is 424 000 €, so the
price ceiling and the €/m² ceiling are essentially the same constraint. When
nothing clears every criterion, the useful answer is *which* criterion each
candidate misses and by how much — that is what this prints.
"""

from __future__ import annotations

import csv
import sys
from pathlib import Path

OUT = Path(__file__).resolve().parent / "out"
CRITERIA = ["t4", "zone", "surface", "prix", "eur_m2", "rer", "livraison", "ptz"]
LABEL = {
    "t4": "T4", "zone": "zone A/Abis", "surface": "≥80 m²", "prix": "≤425 k€",
    "eur_m2": "≤5300 €/m²", "rer": "≤450 m RER", "livraison": "livr. T4-27→29",
    "ptz": "PTZ",
}


def load(path: Path) -> list[dict]:
    with path.open(encoding="utf-8-sig") as fh:
        return list(csv.DictReader(fh))


def num(row: dict, key: str):
    try:
        return float(row[key]) if row.get(key) not in (None, "") else None
    except ValueError:
        return None


def fmt_money(v):
    return f"{v:,.0f} €".replace(",", " ") if v else "—"


def line(row: dict) -> str:
    eur = num(row, "eur_per_m2")
    price = num(row, "price_t4_or_program")
    area = num(row, "area_t4_min")
    walk = num(row, "walk_m")
    return (
        f"{(row['name'] or '?')[:34]:36s} {(row['city'] or '?')[:20]:22s} "
        f"{row.get('zone_abc','') or '?':5s} "
        f"{(str(round(eur)) + ' €/m²') if eur else '—':>11s} "
        f"{fmt_money(price):>11s} "
        f"{(f'{area:.0f} m²' if area else '—'):>7s} "
        f"{(row.get('delivery') or '—'):>9s} "
        f"{(f'{walk:.0f} m' if walk else '—'):>7s} "
        f"{(row.get('station_name') or '')[:18]:20s} {row.get('source','')}"
    )


HEADER = (
    f"{'PROGRAMME':36s} {'VILLE':22s} {'ZONE':5s} {'€/m²':>11s} {'PRIX':>11s} "
    f"{'SURF':>7s} {'LIVR':>9s} {'RER':>7s} {'GARE':20s} SOURCE"
)


def main() -> None:
    path = OUT / "vefa_idf_full.csv"
    if not path.exists():
        sys.exit(f"{path} absent — lancer run.py d'abord")
    rows = load(path)
    print(f"{len(rows)} programmes collectés\n")

    kept = [r for r in rows if r.get("retenu") == "oui"]
    print("=" * 150)
    print(f"RETENUS (tous critères vérifiés) : {len(kept)}")
    print("=" * 150)
    if kept:
        print(HEADER)
        for row in kept[:10]:
            print(line(row))
    else:
        print("aucun programme ne vérifie l'intégralité des critères.")

    # Near misses: everything that fails exactly one criterion, ranked by €/m².
    print()
    print("=" * 150)
    print("PRESQUE-RETENUS (un seul critère en échec, données connues)")
    print("=" * 150)
    near = [
        r for r in rows
        if r.get("retenu") != "oui"
        and len([x for x in (r.get("fails") or "").split("/") if x]) == 1
        and not (r.get("unknown") or "")
    ]
    near.sort(key=lambda r: (num(r, "eur_per_m2") is None, num(r, "eur_per_m2") or 0))
    if near:
        print(HEADER + "   ÉCHEC")
        for row in near[:15]:
            miss = (row.get("fails") or "").strip("/")
            print(line(row) + f"   {LABEL.get(miss, miss)}")
    else:
        print("aucun.")

    # Which criterion is the binding constraint overall.
    print()
    print("Critère bloquant (parmi les programmes où il est vérifiable) :")
    for key in CRITERIA:
        col = f"ok_{key}"
        known = [r for r in rows if r.get(col) in ("oui", "non")]
        fail = [r for r in known if r[col] == "non"]
        unknown = [r for r in rows if r.get(col) == "?"]
        if not rows:
            continue
        rate = (100 * len(fail) / len(known)) if known else 0.0
        print(
            f"   {LABEL[key]:16s} échec {len(fail):5d}/{len(known):5d} ({rate:5.1f}%)"
            f"   non publié: {len(unknown)}"
        )

    with_t4_price = [r for r in rows if num(r, "price_t4_min")]
    with_t4_area = [r for r in rows if num(r, "area_t4_min")]
    with_eur = [r for r in rows if num(r, "eur_per_m2")]
    print(
        f"\nCouverture donnée T4 : prix {len(with_t4_price)}/{len(rows)}, "
        f"surface {len(with_t4_area)}/{len(rows)}, €/m² calculable {len(with_eur)}/{len(rows)}"
    )
    plans = [r for r in rows if r.get("plan_url")]
    print(f"Plans publics (sans formulaire) : {len(plans)}")


if __name__ == "__main__":
    main()
