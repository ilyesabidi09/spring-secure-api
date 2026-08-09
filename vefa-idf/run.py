#!/usr/bin/env python3
"""VEFA / new-build apartment search across Île-de-France.

Pipeline: discover program pages from each site's own sitemaps (robots.txt
enforced on every request) -> extract program facts -> attach the official ABC
zoning -> geocode -> measure the real pedestrian distance to the nearest RER
station -> filter on the search criteria -> write CSV.

Nothing is submitted to any site: this only reads public listing pages.
"""

from __future__ import annotations

import argparse
import csv
import json
import re
import sys
import unicodedata
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from vefa import sources as src
from vefa.geo import (
    Geocoder,
    WalkRouter,
    haversine_m,
    load_rer_stations,
    load_zoning,
    nearest_stations,
)
from vefa.http import Fetcher, RobotsDenied
from vefa.model import Program, detect_kitchen
from vefa.parsing import to_text
from vefa.robots import RobotsGuard

ROOT = Path(__file__).resolve().parent
CACHE = ROOT / ".cache"
OUT = ROOT / "out"

# Search criteria
MAX_PRICE = 425_000
MIN_AREA = 80.0
MAX_EUR_M2 = 5_300
MAX_WALK_M = 450.0
DELIVERY_MIN = (2027, 4)   # Q4 2027
DELIVERY_MAX = (2029, 4)   # end of 2029
ZONES = {"A bis", "Abis", "A BIS", "A"}


def slugify(text: str) -> str:
    text = unicodedata.normalize("NFKD", text or "")
    text = "".join(c for c in text if not unicodedata.combining(c))
    text = re.sub(r"[^a-zA-Z0-9]+", "-", text).strip("-").lower()
    return text


def idf_city_slugs(zoning: dict) -> set[str]:
    return {slugify(v["commune"]) for v in zoning.values() if v.get("commune")}


def zone_for(prog: Program, zoning: dict, by_name: dict) -> str:
    if prog.insee and prog.insee in zoning:
        return zoning[prog.insee]["zone"]
    key = slugify(prog.city)
    if key in by_name:
        return by_name[key]["zone"]
    return ""


def in_delivery_window(year: int | None, quarter: int | None) -> bool | None:
    if not year:
        return None
    q = quarter or 1
    return DELIVERY_MIN <= (year, q) <= DELIVERY_MAX


# ---------------------------------------------------------------------------


def stage_scrape(args) -> list[Program]:
    guard = RobotsGuard()
    fetcher = Fetcher(CACHE / "http", guard=guard, min_interval=args.delay)
    zoning = load_zoning(CACHE / "zoning.json")
    slugs = idf_city_slugs(zoning)

    ctx = src.Context(fetcher=fetcher)
    programs: list[Program] = []
    report: dict[str, dict] = {}

    selected = [c for c in src.ALL_SOURCES if not args.only or c.name in args.only]
    for cls in selected:
        source = cls(slugs) if cls in (src.TrouverUnLogementNeuf, src.Coteneuf) else cls()
        print(f"\n=== {source.name}: discovering…", flush=True)
        try:
            urls = source.discover(ctx)
        except RobotsDenied as exc:
            print(f"    robots.txt forbids {exc}; source skipped")
            report[source.name] = {"urls": 0, "programs": 0, "note": "robots denied"}
            continue
        except Exception as exc:
            print(f"    discovery failed: {exc}")
            report[source.name] = {"urls": 0, "programs": 0, "note": f"error: {exc}"}
            continue

        if args.max_per_source:
            urls = urls[: args.max_per_source]
        print(f"    {len(urls)} program URLs", flush=True)

        found = 0
        denied = 0
        for i, url in enumerate(urls, 1):
            try:
                html = fetcher.get(url)
            except RobotsDenied:
                denied += 1
                continue
            if not html:
                continue
            try:
                parsed = source.parse(ctx, url, html)
            except Exception:
                continue
            text = to_text(html)
            for prog in parsed:
                prog.kitchen_hint = detect_kitchen(text)
                programs.append(prog)
                found += 1
            if i % 25 == 0:
                print(f"      {i}/{len(urls)} … {found} programs", flush=True)

        report[source.name] = {
            "urls": len(urls), "programs": found, "robots_denied": denied
        }
        print(f"    -> {found} programs ({denied} robots-denied)", flush=True)

    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / "scrape_report.json").write_text(
        json.dumps({"sources": report, "http": fetcher.stats}, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )
    (CACHE / "programs_raw.json").write_text(
        json.dumps([p.as_dict() for p in programs], ensure_ascii=False, indent=1),
        encoding="utf-8",
    )
    print(f"\nHTTP: {fetcher.stats}")
    return programs


def stage_geo(programs: list[Program], args) -> list[Program]:
    zoning = load_zoning(CACHE / "zoning.json")
    by_name = {slugify(v["commune"]): v for v in zoning.values() if v.get("commune")}
    stations = load_rer_stations(CACHE / "rer_stations.json")
    geocoder = Geocoder(CACHE / "geocode.json")
    router = WalkRouter(CACHE / "walk.json")
    print(f"\n=== geo stage: {len(stations)} RER stations, {len(programs)} programs")

    routed = 0
    for i, prog in enumerate(programs, 1):
        prog.zone_abc = zone_for(prog, zoning, by_name)

        if prog.lat is None:
            query = " ".join(x for x in [prog.address, prog.postcode, prog.city] if x).strip()
            if query:
                point = geocoder.geocode(query, prog.postcode or None)
                if point:
                    prog.lat, prog.lon = point.lat, point.lon
                    prog.geocode_precision = point.precision
                    prog.insee = prog.insee or point.citycode
        else:
            prog.geocode_precision = prog.geocode_precision or "source"

        if prog.lat is None:
            continue

        # A 450 m criterion needs a real address. When all we could resolve is
        # the commune, the point is its centroid and any distance computed from
        # it would be fiction, so the criterion stays "not verifiable".
        if prog.geocode_precision not in ("source", "housenumber", "street"):
            continue

        # Only programs that could plausibly qualify get pedestrian routing:
        # if the crow-flies distance already exceeds the walking budget, no
        # foot route can be shorter.
        candidates = [
            s for s in nearest_stations(prog.lat, prog.lon, stations, k=3)
            if haversine_m(prog.lat, prog.lon, s["lat"], s["lon"]) <= MAX_WALK_M
        ]
        best = None
        for station in candidates:
            result = router.walk(prog.lat, prog.lon, station["lat"], station["lon"])
            routed += 1
            if not result:
                continue
            metres, minutes = result
            if best is None or metres < best[0]:
                best = (metres, minutes, station)
        if best:
            prog.walk_m, prog.walk_min = round(best[0], 1), round(best[1], 1)
            prog.station_name = best[2]["name"]
            prog.station_line = best[2].get("line") or ""
        if i % 50 == 0:
            geocoder.save()
            router.save()
            print(f"    {i}/{len(programs)} ({routed} foot routes)", flush=True)

    geocoder.save()
    router.save()
    print(f"    pedestrian routes computed: {routed}")
    return programs


def evaluate(prog: Program) -> dict:
    """Per-criterion verdict: True (pass), False (fail), None (not published)."""
    price = prog.price_for_t4() or prog.price_program_min
    area = prog.area_for_t4()
    eur = prog.eur_per_m2()

    zone_ok = None
    if prog.zone_abc:
        zone_ok = prog.zone_abc.replace(" ", "").lower() in {"abis", "a"}

    return {
        "t4": True if prog.has_t4() else (None if not prog.typologies else False),
        "zone": zone_ok,
        "surface": None if area is None else area >= MIN_AREA,
        "prix": None if price is None else price <= MAX_PRICE,
        "eur_m2": None if eur is None else eur <= MAX_EUR_M2,
        "rer": None if prog.walk_m is None else prog.walk_m <= MAX_WALK_M,
        "livraison": in_delivery_window(prog.delivery_year, prog.delivery_quarter),
    }


def deduplicate(programs: list[Program]) -> list[Program]:
    """Collapse repeats of the same programme within a source.

    The same programme is reachable from several listing pages, and aggregators
    republish it under slightly different URLs. Keep whichever copy carries the
    most usable facts.
    """
    def richness(prog: Program) -> tuple:
        return (
            prog.eur_per_m2() is not None,
            prog.lot_count_t4,
            prog.walk_m is not None,
            bool(prog.delivery_year),
            bool(prog.lat),
        )

    best: dict[tuple, Program] = {}
    for prog in programs:
        key = (prog.source, slugify(prog.name), slugify(prog.city))
        current = best.get(key)
        if current is None or richness(prog) > richness(current):
            best[key] = prog
    return list(best.values())


def stage_output(programs: list[Program]) -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    before = len(programs)
    programs = deduplicate(programs)
    print(f"\ndédoublonnage: {before} -> {len(programs)} programmes")
    rows = []
    for prog in programs:
        verdict = evaluate(prog)
        row = prog.as_dict()
        row["price_t4_or_program"] = prog.price_for_t4() or prog.price_program_min
        for key, value in verdict.items():
            row[f"ok_{key}"] = {True: "oui", False: "non", None: "?"}[value]
        row["fails"] = "/".join(k for k, v in verdict.items() if v is False)
        row["unknown"] = "/".join(k for k, v in verdict.items() if v is None)
        row["retenu"] = "oui" if all(v is True for v in verdict.values()) else "non"
        # PTZ is reported, not filtered on: since the 2025 reform the loan
        # covers new-build flats in every zone, so a page that simply does not
        # print the acronym is not evidence of ineligibility.
        row["ok_ptz"] = "oui" if "PTZ" in prog.fiscal else "non mentionné"
        rows.append(row)

    columns = [
        "retenu", "eur_per_m2", "name", "city", "postcode", "zone_abc", "developer",
        "source", "lot_price", "lot_area", "lot_floor", "lot_exposure",
        "lot_available", "lot_count_t4", "price_t4_min", "price_t4_max",
        "price_program_min", "price_program_max", "price_t4_or_program",
        "area_t4_min", "area_t4_max", "area_program_min", "area_program_max",
        "typologies", "delivery", "fiscal", "kitchen_hint", "plan_url",
        "station_name", "station_line", "walk_m", "walk_min", "address",
        "lat", "lon", "geocode_precision", "fails", "unknown", "notes", "url",
    ]
    columns += [c for c in rows[0].keys() if c not in columns] if rows else []

    def sort_key(row):
        return (row["eur_per_m2"] is None, row["eur_per_m2"] or 0)

    rows.sort(key=sort_key)

    with (OUT / "vefa_idf_full.csv").open("w", newline="", encoding="utf-8-sig") as fh:
        writer = csv.DictWriter(fh, fieldnames=columns, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)

    kept = [r for r in rows if r["retenu"] == "oui"]
    with (OUT / "vefa_idf_retenus.csv").open("w", newline="", encoding="utf-8-sig") as fh:
        writer = csv.DictWriter(fh, fieldnames=columns, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(kept)

    print(f"\n=== {len(rows)} programmes -> out/vefa_idf_full.csv")
    print(f"=== {len(kept)} retenus  -> out/vefa_idf_retenus.csv")

    counts: dict[str, int] = {}
    for row in rows:
        for key in row["fails"].split("/"):
            if key:
                counts[key] = counts.get(key, 0) + 1
    print("\nÉliminations par critère:")
    for key, n in sorted(counts.items(), key=lambda x: -x[1]):
        print(f"   {key:12s} {n}")
    unknown: dict[str, int] = {}
    for row in rows:
        for key in row["unknown"].split("/"):
            if key:
                unknown[key] = unknown.get(key, 0) + 1
    print("\nDonnée non publiée (critère non vérifiable):")
    for key, n in sorted(unknown.items(), key=lambda x: -x[1]):
        print(f"   {key:12s} {n}")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--only", nargs="*", default=None, help="restrict to named sources")
    parser.add_argument("--max-per-source", type=int, default=0)
    parser.add_argument("--delay", type=float, default=1.5, help="seconds between hits per host")
    parser.add_argument("--skip-scrape", action="store_true")
    args = parser.parse_args()

    CACHE.mkdir(parents=True, exist_ok=True)
    if args.skip_scrape and (CACHE / "programs_raw.json").exists():
        raw = json.loads((CACHE / "programs_raw.json").read_text(encoding="utf-8"))
        programs = []
        for item in raw:
            prog = Program(source=item["source"], url=item["url"])
            for key, value in item.items():
                if hasattr(prog, key) and key not in ("typologies", "fiscal"):
                    setattr(prog, key, value)
            prog.typologies = [int(x) for x in str(item.get("typologies") or "").split("/") if x]
            prog.fiscal = [x for x in str(item.get("fiscal") or "").split("/") if x]
            programs.append(prog)
    else:
        programs = stage_scrape(args)

    programs = stage_geo(programs, args)
    stage_output(programs)


if __name__ == "__main__":
    main()
