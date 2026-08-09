"""Reference data and geographic computations.

Sources, all public and key-free:

* ``data.iledefrance.fr`` — official ABC zoning per commune (zone A bis / A / B1
  ...), which drives both the zone filter and PTZ eligibility.
* ``data.iledefrance-mobilites.fr`` — coordinates of every RER station.
* ``api-adresse.data.gouv.fr`` — Base Adresse Nationale geocoder.
* ``valhalla1.openstreetmap.de`` — pedestrian routing.

Note on routers: the public OSRM demo server only has the *car* profile loaded
and silently answers ``/route/v1/foot/`` with car routing (a 2.1 km answer in
405 s is 18 km/h, not walking pace), so it cannot be used for a walking-distance
criterion. Valhalla's ``pedestrian`` costing is genuine foot routing.
"""

from __future__ import annotations

import json
import math
import time
import urllib.parse
import urllib.request
from dataclasses import dataclass
from pathlib import Path

ZONING_API = (
    "https://data.iledefrance.fr/api/explore/v2.1/catalog/datasets/"
    "logement-liste-des-communes-selon-le-zonage-abc/records"
)
STATIONS_API = (
    "https://data.iledefrance-mobilites.fr/api/explore/v2.1/catalog/datasets/"
    "emplacement-des-gares-idf/records"
)
BAN_API = "https://api-adresse.data.gouv.fr/search/"
VALHALLA_API = "https://valhalla1.openstreetmap.de/route"

HEADERS = {"User-Agent": "vefa-idf-research/1.0", "Accept": "application/json"}


def _get_json(url: str, params: dict | None = None, timeout: int = 60):
    if params:
        url = f"{url}?{urllib.parse.urlencode(params)}"
    req = urllib.request.Request(url, headers=HEADERS)
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return json.loads(resp.read().decode("utf-8"))


def _post_json(url: str, payload: dict, timeout: int = 60):
    data = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(
        url, data=data, headers={**HEADERS, "Content-Type": "application/json"}
    )
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return json.loads(resp.read().decode("utf-8"))


def haversine_m(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    r = 6371000.0
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp = math.radians(lat2 - lat1)
    dl = math.radians(lon2 - lon1)
    a = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * r * math.asin(math.sqrt(a))


# --------------------------------------------------------------------------
# Reference datasets
# --------------------------------------------------------------------------

def load_zoning(cache: Path) -> dict[str, dict]:
    """INSEE code -> {commune, dept, zone}. Cached on disk."""
    cache = Path(cache)
    if cache.exists():
        return json.loads(cache.read_text(encoding="utf-8"))

    out: dict[str, dict] = {}
    offset = 0
    zone_field = None
    while True:
        payload = _get_json(
            ZONING_API,
            {"limit": 100, "offset": offset, "select": "codgeo,dep,libgeo,*"},
        )
        results = payload.get("results", [])
        if not results:
            break
        if zone_field is None:
            for key in results[0]:
                if key.startswith("zonage_en_vigueur"):
                    zone_field = key
                    break
        for row in results:
            code = str(row.get("codgeo") or "").strip()
            if not code:
                continue
            out[code] = {
                "commune": row.get("libgeo"),
                "dept": row.get("dep"),
                "zone": (row.get(zone_field) or "").strip() if zone_field else "",
            }
        offset += 100
        if offset >= payload.get("total_count", 0) or offset > 5000:
            break
        time.sleep(0.2)

    cache.parent.mkdir(parents=True, exist_ok=True)
    cache.write_text(json.dumps(out, ensure_ascii=False), encoding="utf-8")
    return out


def load_rer_stations(cache: Path) -> list[dict]:
    """Every RER station with coordinates. Cached on disk."""
    cache = Path(cache)
    if cache.exists():
        return json.loads(cache.read_text(encoding="utf-8"))

    stations: list[dict] = []
    offset = 0
    while True:
        payload = _get_json(
            STATIONS_API,
            {
                "where": "mode='RER'",
                "limit": 100,
                "offset": offset,
                "select": "nom_gares,res_com,indice_lig,geo_point_2d",
            },
        )
        results = payload.get("results", [])
        if not results:
            break
        for row in results:
            point = row.get("geo_point_2d") or {}
            if point.get("lat") is None:
                continue
            stations.append(
                {
                    "name": row.get("nom_gares"),
                    "line": row.get("indice_lig"),
                    "network": row.get("res_com"),
                    "lat": point["lat"],
                    "lon": point["lon"],
                }
            )
        offset += 100
        if offset >= payload.get("total_count", 0) or offset > 2000:
            break
        time.sleep(0.2)

    # The dataset holds one row per line serving a station; collapse duplicates
    # so "Nanterre-Université" is not routed to three times.
    merged: dict[tuple, dict] = {}
    for st in stations:
        key = (st["name"], round(st["lat"], 5), round(st["lon"], 5))
        if key in merged:
            existing = merged[key]["line"] or ""
            if st["line"] and st["line"] not in existing:
                merged[key]["line"] = f"{existing}/{st['line']}".strip("/")
        else:
            merged[key] = dict(st)
    out = list(merged.values())

    cache.parent.mkdir(parents=True, exist_ok=True)
    cache.write_text(json.dumps(out, ensure_ascii=False), encoding="utf-8")
    return out


# --------------------------------------------------------------------------
# Geocoding and routing
# --------------------------------------------------------------------------

@dataclass
class GeoPoint:
    lat: float
    lon: float
    label: str
    score: float
    citycode: str
    precision: str


class Geocoder:
    """BAN geocoder with an on-disk memo."""

    def __init__(self, cache_file: Path) -> None:
        self.cache_file = Path(cache_file)
        self._cache: dict[str, dict | None] = {}
        if self.cache_file.exists():
            self._cache = json.loads(self.cache_file.read_text(encoding="utf-8"))

    def save(self) -> None:
        self.cache_file.parent.mkdir(parents=True, exist_ok=True)
        self.cache_file.write_text(
            json.dumps(self._cache, ensure_ascii=False), encoding="utf-8"
        )

    def geocode(self, query: str, postcode: str | None = None) -> GeoPoint | None:
        key = f"{query}|{postcode or ''}"
        if key not in self._cache:
            params = {"q": query, "limit": 1}
            if postcode:
                params["postcode"] = postcode
            try:
                payload = _get_json(BAN_API, params, timeout=30)
                features = payload.get("features") or []
                self._cache[key] = features[0] if features else None
            except Exception:
                self._cache[key] = None
            time.sleep(0.1)

        feature = self._cache[key]
        if not feature:
            return None
        props = feature["properties"]
        lon, lat = feature["geometry"]["coordinates"]
        return GeoPoint(
            lat=lat,
            lon=lon,
            label=props.get("label", ""),
            score=props.get("score", 0.0),
            citycode=props.get("citycode", ""),
            precision=props.get("type", ""),
        )


class WalkRouter:
    """Valhalla pedestrian routing with an on-disk memo."""

    def __init__(self, cache_file: Path, min_interval: float = 1.1) -> None:
        self.cache_file = Path(cache_file)
        self._cache: dict[str, dict | None] = {}
        self.min_interval = min_interval
        self._last = 0.0
        if self.cache_file.exists():
            self._cache = json.loads(self.cache_file.read_text(encoding="utf-8"))

    def save(self) -> None:
        self.cache_file.parent.mkdir(parents=True, exist_ok=True)
        self.cache_file.write_text(
            json.dumps(self._cache, ensure_ascii=False), encoding="utf-8"
        )

    def walk(
        self, lat1: float, lon1: float, lat2: float, lon2: float
    ) -> tuple[float, float] | None:
        """Return (metres, minutes) on foot, or None if routing failed."""
        key = f"{lat1:.6f},{lon1:.6f}->{lat2:.6f},{lon2:.6f}"
        if key not in self._cache:
            delta = time.monotonic() - self._last
            if delta < self.min_interval:
                time.sleep(self.min_interval - delta)
            self._last = time.monotonic()
            payload = {
                "locations": [
                    {"lat": lat1, "lon": lon1},
                    {"lat": lat2, "lon": lon2},
                ],
                "costing": "pedestrian",
                "directions_options": {"units": "kilometers"},
            }
            try:
                data = _post_json(VALHALLA_API, payload, timeout=45)
                summary = data["trip"]["summary"]
                self._cache[key] = {
                    "m": summary["length"] * 1000.0,
                    "min": summary["time"] / 60.0,
                }
            except Exception:
                self._cache[key] = None

        entry = self._cache[key]
        if not entry:
            return None
        return entry["m"], entry["min"]


def nearest_stations(
    lat: float, lon: float, stations: list[dict], k: int = 3
) -> list[dict]:
    """The k closest stations as the crow flies, used to pre-select candidates
    before spending pedestrian-routing calls on them."""
    ranked = sorted(
        stations, key=lambda s: haversine_m(lat, lon, s["lat"], s["lon"])
    )
    return ranked[:k]
