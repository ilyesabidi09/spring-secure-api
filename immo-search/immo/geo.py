"""Stations, zoning, geocoding and pedestrian routing.

Same public data sources as the VEFA pipeline, widened from RER to every rail
mode (RER, métro, Transilien, tramway) because a search tool should let you ask
for "5 minutes from any station", not only from an RER.
"""

from __future__ import annotations

import json
import math
import ssl
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

STATIONS_API = (
    "https://data.iledefrance-mobilites.fr/api/explore/v2.1/catalog/datasets/"
    "emplacement-des-gares-idf/records"
)
ZONING_API = (
    "https://data.iledefrance.fr/api/explore/v2.1/catalog/datasets/"
    "logement-liste-des-communes-selon-le-zonage-abc/records"
)
BAN_API = "https://api-adresse.data.gouv.fr/search/"
VALHALLA_API = "https://valhalla1.openstreetmap.de/route"
HEADERS = {"User-Agent": "immo-search/1.0", "Accept": "application/json"}

MODE_MAP = {
    "RER": "RER", "METRO": "METRO", "TRAIN": "TRAIN", "TRAMWAY": "TRAM",
    "TRAM": "TRAM", "VAL": "TRAIN", "TER": "TRAIN",
}


def ssl_context() -> ssl.SSLContext:
    """Verified TLS, preferring certifi's roots when they are installed.

    Some of these public hosts serve a chain containing an expired cross-signed
    root. Trust stores that only know the old path reject it — Windows' store
    does, which is why one host fails while another on the same machine works.
    certifi carries the modern roots and resolves it. Verification stays on
    either way: an expired chain is exactly the thing you want TLS to catch.
    """
    try:
        import certifi
        return ssl.create_default_context(cafile=certifi.where())
    except Exception:
        return ssl.create_default_context()


CERT_HELP = (
    "\nÉchec de vérification TLS. Le certificat de cet hôte n'est pas validé par\n"
    "le magasin de certificats de votre système. Correctif :\n"
    "    py -m pip install certifi        (Windows)\n"
    "    python3 -m pip install certifi   (macOS / Linux)\n"
    "puis relancer. Ne désactivez pas la vérification TLS.\n"
)


def _open(req, timeout: int):
    try:
        return urllib.request.urlopen(req, timeout=timeout, context=ssl_context())
    except urllib.error.URLError as exc:
        if isinstance(getattr(exc, "reason", None), ssl.SSLCertVerificationError):
            raise RuntimeError(f"{req.full_url}\n{CERT_HELP}") from exc
        raise


def _get_json(url: str, params: dict | None = None, timeout: int = 60):
    if params:
        url = f"{url}?{urllib.parse.urlencode(params)}"
    req = urllib.request.Request(url, headers=HEADERS)
    with _open(req, timeout) as resp:
        return json.loads(resp.read().decode("utf-8"))


def _post_json(url: str, payload: dict, timeout: int = 60):
    data = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(
        url, data=data, headers={**HEADERS, "Content-Type": "application/json"}
    )
    with _open(req, timeout) as resp:
        return json.loads(resp.read().decode("utf-8"))


def haversine_m(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    radius = 6371000.0
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dphi = math.radians(lat2 - lat1)
    dlambda = math.radians(lon2 - lon1)
    a = math.sin(dphi / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dlambda / 2) ** 2
    return 2 * radius * math.asin(math.sqrt(a))


REFDATA = Path(__file__).resolve().parent.parent / "refdata"


def _seed(cache: Path, name: str):
    """Copy of a reference dataset shipped with the repo, if we have one."""
    seed = REFDATA / name
    if seed.exists():
        payload = json.loads(seed.read_text(encoding="utf-8"))
        cache.parent.mkdir(parents=True, exist_ok=True)
        cache.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
        return payload
    return None


def load_stations(cache: Path) -> list[dict]:
    """Every rail station in Île-de-France, one row per stop, modes merged."""
    cache = Path(cache)
    if cache.exists():
        return json.loads(cache.read_text(encoding="utf-8"))
    seeded = _seed(cache, "stations.json")
    if seeded is not None:
        return seeded

    raw: list[dict] = []
    offset = 0
    while True:
        payload = _get_json(
            STATIONS_API,
            {
                "limit": 100, "offset": offset,
                "select": "nom_gares,res_com,indice_lig,mode,geo_point_2d",
            },
        )
        results = payload.get("results", [])
        if not results:
            break
        for row in results:
            point = row.get("geo_point_2d") or {}
            if point.get("lat") is None:
                continue
            mode = MODE_MAP.get((row.get("mode") or "").upper().strip())
            if not mode:
                continue
            raw.append(
                {
                    "name": row.get("nom_gares"),
                    "mode": mode,
                    "line": (row.get("indice_lig") or "").strip(),
                    "lat": point["lat"],
                    "lon": point["lon"],
                }
            )
        offset += 100
        if offset >= payload.get("total_count", 0) or offset > 5000:
            break
        time.sleep(0.15)

    merged: dict[tuple, dict] = {}
    for station in raw:
        key = (station["name"], station["mode"], round(station["lat"], 5), round(station["lon"], 5))
        if key in merged:
            lines = merged[key]["line"]
            if station["line"] and station["line"] not in lines.split("/"):
                merged[key]["line"] = f"{lines}/{station['line']}".strip("/")
        else:
            merged[key] = dict(station)
    out = sorted(merged.values(), key=lambda s: (s["mode"], s["name"]))

    cache.parent.mkdir(parents=True, exist_ok=True)
    cache.write_text(json.dumps(out, ensure_ascii=False), encoding="utf-8")
    return out


def load_zoning(cache: Path) -> dict[str, dict]:
    cache = Path(cache)
    if cache.exists():
        return json.loads(cache.read_text(encoding="utf-8"))
    seeded = _seed(cache, "zoning.json")
    if seeded is not None:
        return seeded
    out: dict[str, dict] = {}
    offset, zone_field = 0, None
    while True:
        payload = _get_json(ZONING_API, {"limit": 100, "offset": offset})
        results = payload.get("results", [])
        if not results:
            break
        if zone_field is None:
            zone_field = next(
                (k for k in results[0] if k.startswith("zonage_en_vigueur")), None
            )
        for row in results:
            code = str(row.get("codgeo") or "").strip()
            if code:
                out[code] = {
                    "commune": row.get("libgeo"),
                    "dept": row.get("dep"),
                    "zone": (row.get(zone_field) or "").strip() if zone_field else "",
                }
        offset += 100
        if offset >= payload.get("total_count", 0) or offset > 5000:
            break
        time.sleep(0.15)
    cache.parent.mkdir(parents=True, exist_ok=True)
    cache.write_text(json.dumps(out, ensure_ascii=False), encoding="utf-8")
    return out


class Geocoder:
    def __init__(self, cache_file: Path) -> None:
        self.cache_file = Path(cache_file)
        self._cache: dict = {}
        if self.cache_file.exists():
            self._cache = json.loads(self.cache_file.read_text(encoding="utf-8"))

    def save(self) -> None:
        self.cache_file.parent.mkdir(parents=True, exist_ok=True)
        self.cache_file.write_text(
            json.dumps(self._cache, ensure_ascii=False), encoding="utf-8"
        )

    def geocode(self, query: str, postcode: str | None = None) -> dict | None:
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
            time.sleep(0.08)
        feature = self._cache[key]
        if not feature:
            return None
        lon, lat = feature["geometry"]["coordinates"]
        props = feature["properties"]
        return {
            "lat": lat, "lon": lon, "precision": props.get("type", ""),
            "citycode": props.get("citycode", ""), "label": props.get("label", ""),
        }


class WalkRouter:
    """Valhalla pedestrian routing, memoised on disk.

    The public OSRM demo only has the car profile loaded and answers
    ``/route/v1/foot/`` with car routing, so it cannot back a walking filter.
    """

    def __init__(self, cache_file: Path, min_interval: float = 1.05) -> None:
        self.cache_file = Path(cache_file)
        self._cache: dict = {}
        self.min_interval = min_interval
        self._last = 0.0
        if self.cache_file.exists():
            self._cache = json.loads(self.cache_file.read_text(encoding="utf-8"))

    def save(self) -> None:
        self.cache_file.parent.mkdir(parents=True, exist_ok=True)
        self.cache_file.write_text(
            json.dumps(self._cache, ensure_ascii=False), encoding="utf-8"
        )

    def walk(self, lat1, lon1, lat2, lon2) -> tuple[float, float] | None:
        key = f"{lat1:.6f},{lon1:.6f}->{lat2:.6f},{lon2:.6f}"
        if key not in self._cache:
            delta = time.monotonic() - self._last
            if delta < self.min_interval:
                time.sleep(self.min_interval - delta)
            self._last = time.monotonic()
            try:
                data = _post_json(
                    VALHALLA_API,
                    {
                        "locations": [
                            {"lat": lat1, "lon": lon1}, {"lat": lat2, "lon": lon2}
                        ],
                        "costing": "pedestrian",
                        "directions_options": {"units": "kilometers"},
                    },
                    timeout=45,
                )
                summary = data["trip"]["summary"]
                self._cache[key] = {
                    "m": summary["length"] * 1000.0, "min": summary["time"] / 60.0
                }
            except Exception:
                self._cache[key] = None
        entry = self._cache[key]
        return (entry["m"], entry["min"]) if entry else None


def nearest(lat: float, lon: float, stations: list[dict], k: int = 6) -> list[dict]:
    ranked = sorted(stations, key=lambda s: haversine_m(lat, lon, s["lat"], s["lon"]))
    return ranked[:k]
