"""Loading listings into the index.

Two ingesters, deliberately kept apart because the records mean different
things — a marketed VEFA price and a settled DVF price must never be averaged
together by accident.
"""

from __future__ import annotations

import csv
import gzip
import io
import json
import re
import urllib.request
from pathlib import Path

from .model import (
    KIND_ANCIEN,
    KIND_NEUF,
    Listing,
    Station,
    detect_features,
    make_id,
    price_plausibility,
)

DVF_BASE = "https://files.data.gouv.fr/geo-dvf/latest/csv"
IDF_DEPTS = ["75", "77", "78", "91", "92", "93", "94", "95"]
HEADERS = {"User-Agent": "immo-search/1.0"}


# ---------------------------------------------------------------------------
# VEFA (marketed new-build programmes), from the vefa-idf pipeline output
# ---------------------------------------------------------------------------

def _f(row: dict, key: str) -> float | None:
    raw = (row.get(key) or "").strip()
    if not raw:
        return None
    try:
        return float(raw)
    except ValueError:
        return None


def load_vefa_csv(path: Path) -> list[Listing]:
    """Read vefa_idf_full.csv into listings.

    The €/m² is only carried over when the pipeline matched a price and a
    surface on the same lot; otherwise surface and price stay separate and the
    listing simply has no €/m².
    """
    path = Path(path)
    if not path.exists():
        return []
    out: list[Listing] = []
    with path.open(encoding="utf-8-sig") as fh:
        for row in csv.DictReader(fh):
            name = (row.get("name") or "").strip()
            if not name:
                continue
            listing = Listing(
                id=make_id("vefa", row.get("source"), name, row.get("city")),
                kind=KIND_NEUF,
                source=row.get("source") or "vefa",
                url=row.get("url") or "",
                name=name,
                developer=(row.get("developer") or "").strip(),
                address=(row.get("address") or "").strip(),
                city=(row.get("city") or "").strip(),
                postcode=(row.get("postcode") or "").strip(),
                insee=(row.get("insee") or "").strip(),
                dept=(row.get("dept") or "").strip(),
                zone_abc=(row.get("zone_abc") or "").strip(),
                lat=_f(row, "lat"),
                lon=_f(row, "lon"),
                address_precision=(row.get("geocode_precision") or "").strip(),
                floor=(row.get("lot_floor") or "").strip(),
                exposure=(row.get("lot_exposure") or "").strip(),
                kitchen_hint=(row.get("kitchen_hint") or "").strip(),
                plan_url=(row.get("plan_url") or "").strip(),
                notes=(row.get("notes") or "").strip(),
            )
            available = (row.get("lot_available") or "").strip().lower()
            listing.available = {"oui": True, "non": False}.get(available)

            lot_price, lot_area = _f(row, "lot_price"), _f(row, "lot_area")
            if lot_price and lot_area:
                listing.price, listing.surface = lot_price, lot_area
                listing.rooms = 4  # the pipeline only pairs lots on the T4 tier
                listing.surface_is_carrez = True
            else:
                listing.price = _f(row, "price_t4_min") or _f(row, "price_program_min")
                listing.surface = _f(row, "area_t4_min")
                typologies = [
                    int(t) for t in (row.get("typologies") or "").split("/") if t.isdigit()
                ]
                listing.rooms = 4 if 4 in typologies else (typologies[-1] if typologies else None)

            delivery = (row.get("delivery") or "").strip()
            m = re.match(r"T([1-4])\s*(\d{4})", delivery)
            if m:
                listing.delivery_quarter, listing.delivery_year = int(m.group(1)), int(m.group(2))
            elif re.match(r"^\d{4}$", delivery):
                listing.delivery_year = int(delivery)

            listing.fiscal = [f for f in (row.get("fiscal") or "").split("/") if f]
            listing.features = detect_features(
                " ".join([row.get("notes") or "", row.get("kitchen_hint") or "", name])
            )
            for key in ("photos", "photo_urls"):
                if row.get(key):
                    listing.photos = [u for u in row[key].split("|") if u.startswith("http")]
                    break

            station = (row.get("station_name") or "").strip()
            if station:
                listing.stations = [
                    Station(
                        name=station,
                        mode="RER",
                        line=(row.get("station_line") or "").strip(),
                        walk_m=_f(row, "walk_m"),
                        walk_min=_f(row, "walk_min"),
                    )
                ]
            out.append(listing)
    return out


def load_vefa_json(path: Path) -> list[Listing]:
    """Richer path: the pipeline's raw JSON, which keeps photo lists intact."""
    path = Path(path)
    if not path.exists():
        return []
    rows = json.loads(path.read_text(encoding="utf-8"))
    tmp = Path(str(path) + ".csv")
    if not rows:
        return []
    with tmp.open("w", newline="", encoding="utf-8-sig") as fh:
        writer = csv.DictWriter(fh, fieldnames=sorted({k for r in rows for k in r}))
        writer.writeheader()
        for row in rows:
            writer.writerow({k: ("" if v is None else v) for k, v in row.items()})
    try:
        return load_vefa_csv(tmp)
    finally:
        tmp.unlink(missing_ok=True)


# ---------------------------------------------------------------------------
# DVF (completed sales)
# ---------------------------------------------------------------------------

def _download_dvf(dept: str, year: int, cache_dir: Path) -> Path | None:
    cache_dir = Path(cache_dir)
    cache_dir.mkdir(parents=True, exist_ok=True)
    target = cache_dir / f"dvf-{year}-{dept}.csv.gz"
    if target.exists() and target.stat().st_size > 0:
        return target
    url = f"{DVF_BASE}/{year}/departements/{dept}.csv.gz"
    try:
        req = urllib.request.Request(url, headers=HEADERS)
        with urllib.request.urlopen(req, timeout=180) as resp:
            data = resp.read()
        target.write_bytes(data)
        return target
    except Exception:
        return None


def _carrez(row: dict) -> float | None:
    total = 0.0
    for i in range(1, 6):
        raw = (row.get(f"lot{i}_surface_carrez") or "").strip()
        if raw:
            try:
                total += float(raw)
            except ValueError:
                pass
    return total or None


def fetch_dvf(
    depts: list[str] | None = None,
    years: list[int] | None = None,
    cache_dir: Path = Path("data/dvf"),
    max_rows: int | None = None,
) -> list[Listing]:
    """Apartment sales from the DVF register.

    Only single-apartment mutations are kept. When a sale bundles several flats
    under one price, that price cannot be attributed to any one of them, and
    dividing it by a single flat's surface would invent a €/m² that never
    existed — so those mutations are dropped rather than approximated.
    """
    depts = depts or IDF_DEPTS
    years = years or [2024]
    out: list[Listing] = []

    for year in years:
        for dept in depts:
            path = _download_dvf(dept, year, cache_dir)
            if not path:
                continue
            with gzip.open(path, "rt", encoding="utf-8", errors="replace") as fh:
                mutations: dict[str, list[dict]] = {}
                for row in csv.DictReader(fh):
                    if row.get("nature_mutation") not in ("Vente", "Vente en l'état futur d'achèvement"):
                        continue
                    mutations.setdefault(row["id_mutation"], []).append(row)

            for mutation_id, rows in mutations.items():
                flats = [r for r in rows if r.get("type_local") == "Appartement"]
                if len(flats) != 1:
                    continue
                row = flats[0]
                try:
                    price = float(row["valeur_fonciere"])
                except (KeyError, ValueError, TypeError):
                    continue
                if price <= 0:
                    continue

                carrez = _carrez(row)
                surface = carrez
                if not surface:
                    try:
                        surface = float(row["surface_reelle_bati"])
                    except (KeyError, ValueError, TypeError):
                        surface = None
                if not surface or surface <= 0:
                    continue

                rooms = None
                try:
                    rooms = int(float(row["nombre_pieces_principales"]))
                except (KeyError, ValueError, TypeError):
                    pass

                street = " ".join(
                    x for x in [
                        (row.get("adresse_numero") or "").strip(),
                        (row.get("adresse_suffixe") or "").strip(),
                        (row.get("adresse_nom_voie") or "").strip(),
                    ] if x
                )
                annexes = [r.get("type_local") or "" for r in rows if r is not row]
                features = detect_features(" ".join(annexes))
                if any("épendance" in a for a in annexes):
                    features = sorted(set(features) | {"cave"})

                lat = lon = None
                try:
                    lat = float(row["latitude"]); lon = float(row["longitude"])
                except (KeyError, ValueError, TypeError):
                    pass

                is_vefa = row["nature_mutation"].startswith("Vente en l'état")
                listing = Listing(
                    id=make_id("dvf", mutation_id, row.get("id_parcelle")),
                    kind=KIND_ANCIEN,
                    source="dvf",
                    url="https://app.dvf.etalab.gouv.fr/",
                    name=f"{rooms or '?'} pièces · {street or row.get('nom_commune', '')}",
                    address=street,
                    city=(row.get("nom_commune") or "").strip(),
                    postcode=(row.get("code_postal") or "").strip(),
                    insee=(row.get("code_commune") or "").strip(),
                    dept=(row.get("code_departement") or "").strip(),
                    lat=lat, lon=lon,
                    address_precision="source" if lat else "",
                    rooms=rooms,
                    surface=round(surface, 2),
                    surface_is_carrez=bool(carrez),
                    price=price,
                    sale_date=(row.get("date_mutation") or "").strip(),
                    features=features,
                    notes="vente VEFA enregistrée" if is_vefa else "",
                )
                listing.price_flag = price_plausibility(price, surface)
                out.append(listing)
                if max_rows and len(out) >= max_rows:
                    return out
    return out
