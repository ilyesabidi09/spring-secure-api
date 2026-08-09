#!/usr/bin/env python3
"""Build the search index: ingest, enrich, persist.

    python3 build_index.py --dvf-years 2024 2025 --dvf-depts 94 93 --walk

Straight-line distance to the six nearest stations is computed for every
listing (local, instant). Real pedestrian routing is reserved for the marketed
programmes: routing a hundred thousand past sales through a public API would
take days, and nobody picks a price comparable by walking time.
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from immo.geo import Geocoder, WalkRouter, haversine_m, load_stations, load_zoning, nearest
from immo.ingest import IDF_DEPTS, fetch_dvf, load_vefa_csv
from immo.model import KIND_NEUF, Listing, Station, flag_against_local_median, slugify

ROOT = Path(__file__).resolve().parent
DATA = ROOT / "data"
VEFA_CSV = ROOT.parent / "vefa-idf" / "out" / "vefa_idf_full.csv"


def enrich_zoning(listings: list[Listing], zoning: dict) -> None:
    by_name = {slugify(v["commune"]): v for v in zoning.values() if v.get("commune")}
    for listing in listings:
        if listing.zone_abc:
            continue
        entry = zoning.get(listing.insee) or by_name.get(slugify(listing.city))
        if entry:
            listing.zone_abc = entry.get("zone", "")
            listing.dept = listing.dept or entry.get("dept", "")


def enrich_stations(listings: list[Listing], stations: list[dict], k: int = 6) -> None:
    for listing in listings:
        if listing.lat is None:
            continue
        existing = {(s.name, s.mode) for s in listing.stations}
        for station in nearest(listing.lat, listing.lon, stations, k=k):
            key = (station["name"], station["mode"])
            crow = haversine_m(listing.lat, listing.lon, station["lat"], station["lon"])
            if key in existing:
                for s in listing.stations:
                    if (s.name, s.mode) == key and s.crow_m is None:
                        s.crow_m = round(crow, 1)
                continue
            listing.stations.append(
                Station(
                    name=station["name"], mode=station["mode"], line=station["line"],
                    crow_m=round(crow, 1),
                )
            )
        listing.stations.sort(key=lambda s: s.crow_m if s.crow_m is not None else 1e12)


def enrich_walking(
    listings: list[Listing], router: WalkRouter, max_crow: float = 1200.0, budget: int = 4000
) -> int:
    """Route the plausible pairs only: a walk is never shorter than the line."""
    calls = 0
    for listing in listings:
        if listing.lat is None:
            continue
        for station in listing.stations:
            if calls >= budget:
                return calls
            if station.crow_m is None or station.crow_m > max_crow:
                continue
            if station.walk_m is not None:
                continue
            result = router.walk(
                listing.lat, listing.lon,
                *_station_coords(station, listing),
            )
            calls += 1
            if result:
                station.walk_m, station.walk_min = round(result[0], 1), round(result[1], 1)
        if calls and calls % 200 == 0:
            router.save()
    return calls


_STATION_INDEX: dict[tuple, tuple[float, float]] = {}


def _station_coords(station: Station, listing: Listing) -> tuple[float, float]:
    return _STATION_INDEX[(station.name, station.mode)]


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dvf-years", nargs="*", type=int, default=[2024])
    parser.add_argument("--dvf-depts", nargs="*", default=IDF_DEPTS)
    parser.add_argument("--dvf-max", type=int, default=0, help="0 = pas de limite")
    parser.add_argument("--no-dvf", action="store_true")
    parser.add_argument("--walk", action="store_true", help="router les programmes neufs à pied")
    parser.add_argument("--walk-budget", type=int, default=4000)
    parser.add_argument("--out", default=str(DATA / "index.json"))
    args = parser.parse_args()

    DATA.mkdir(parents=True, exist_ok=True)
    started = time.time()

    print("→ zonage ABC…", flush=True)
    zoning = load_zoning(DATA / "zoning.json")
    print(f"  {len(zoning)} communes")

    print("→ gares (tous modes)…", flush=True)
    stations = load_stations(DATA / "stations.json")
    for station in stations:
        _STATION_INDEX[(station["name"], station["mode"])] = (station["lat"], station["lon"])
    modes: dict[str, int] = {}
    for s in stations:
        modes[s["mode"]] = modes.get(s["mode"], 0) + 1
    print(f"  {len(stations)} arrêts {modes}")

    listings: list[Listing] = []

    print(f"→ programmes neufs ({VEFA_CSV.name})…", flush=True)
    vefa = load_vefa_csv(VEFA_CSV)
    print(f"  {len(vefa)} programmes")
    listings.extend(vefa)

    if not args.no_dvf:
        print(f"→ DVF {args.dvf_years} dépts {args.dvf_depts}…", flush=True)
        dvf = fetch_dvf(
            depts=args.dvf_depts, years=args.dvf_years,
            cache_dir=DATA / "dvf", max_rows=args.dvf_max or None,
        )
        flagged = flag_against_local_median(dvf)
        atypical = sum(1 for d in dvf if d.price_flag)
        print(
            f"  {len(dvf)} ventes d'appartements "
            f"({atypical} mutations atypiques écartées par défaut, dont {flagged} "
            f"repérées par rapport à leur médiane communale)"
        )
        listings.extend(dvf)

    print("→ enrichissement zonage / gares…", flush=True)
    enrich_zoning(listings, zoning)
    enrich_stations(listings, stations)

    if args.walk:
        print("→ distances piétonnes (programmes neufs)…", flush=True)
        router = WalkRouter(DATA / "walk.json")
        neufs = [l for l in listings if l.kind == KIND_NEUF]
        calls = enrich_walking(neufs, router, budget=args.walk_budget)
        router.save()
        routed = sum(1 for l in neufs for s in l.stations if s.walk_m is not None)
        print(f"  {calls} appels, {routed} trajets connus")

    payload = {
        "built_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
        "sources": {
            "neuf": "pages de listing publiques (9 sites), prix affichés",
            "ancien": f"DVF {args.dvf_years} — ventes enregistrées, prix réels",
        },
        "listings": [l.as_dict() for l in listings],
    }
    out = Path(args.out)
    out.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
    size = out.stat().st_size / 1e6
    print(
        f"\n✓ {len(listings)} biens → {out} ({size:.1f} Mo) "
        f"en {time.time() - started:.0f}s"
    )


if __name__ == "__main__":
    main()
