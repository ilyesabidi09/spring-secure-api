"""The unified listing record.

Two very different things live in the same index and the distinction must never
blur, because confusing them would compare an asking price with a settled one:

* ``kind="neuf"`` — a VEFA programme currently marketed. The price is what the
  developer is asking today.
* ``kind="ancien"`` — a completed sale from the DVF register. The price is what
  a flat actually sold for, months ago. It is a comparable, not an offer.

Every field is optional except ``id``/``kind``/``source``: sources publish very
different subsets, and a missing value stays ``None`` rather than being guessed,
so a filter can tell "does not match" apart from "not published".
"""

from __future__ import annotations

import hashlib
import unicodedata
import re
from dataclasses import dataclass, field, asdict, fields

KIND_NEUF = "neuf"
KIND_ANCIEN = "ancien"

FEATURES = [
    "parking", "balcon", "terrasse", "jardin", "cave", "ascenseur",
    "duplex", "rez-de-jardin", "loggia", "piscine",
]

FEATURE_PATTERNS = {
    "parking": r"\bparking|\bbox\b|\bgarage\b|place de stationnement",
    "balcon": r"\bbalcons?\b",
    "terrasse": r"\bterrasses?\b|\brooftop\b",
    "jardin": r"\bjardins?\s+privatifs?\b|\bjardin\b",
    "cave": r"\bcaves?\b|\bcellier\b",
    "ascenseur": r"\bascenseur\b",
    "duplex": r"\bduplex\b",
    "rez-de-jardin": r"rez[- ]de[- ]jardin",
    "loggia": r"\bloggias?\b",
    "piscine": r"\bpiscine\b",
}


def slugify(text: str) -> str:
    text = unicodedata.normalize("NFKD", text or "")
    text = "".join(c for c in text if not unicodedata.combining(c))
    return re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")


def detect_features(text: str) -> list[str]:
    low = (text or "").lower()
    return [name for name, pattern in FEATURE_PATTERNS.items() if re.search(pattern, low)]


@dataclass(slots=True)
class Station:
    name: str
    mode: str          # RER, METRO, TRAIN, TRAM
    line: str
    walk_m: float | None = None
    walk_min: float | None = None
    crow_m: float | None = None

    def as_dict(self) -> dict:
        return asdict(self)


@dataclass(slots=True)
class Listing:
    id: str
    kind: str
    source: str
    url: str = ""

    name: str = ""
    developer: str = ""

    address: str = ""
    city: str = ""
    postcode: str = ""
    insee: str = ""
    dept: str = ""
    zone_abc: str = ""
    lat: float | None = None
    lon: float | None = None
    address_precision: str = ""   # housenumber | street | municipality | source

    rooms: int | None = None
    surface: float | None = None          # Carrez when the source gives it
    surface_is_carrez: bool = False
    price: float | None = None
    floor: str = ""
    exposure: str = ""
    available: bool | None = None

    delivery_year: int | None = None
    delivery_quarter: int | None = None
    sale_date: str = ""                   # ISO date, ancien only

    fiscal: list[str] = field(default_factory=list)
    features: list[str] = field(default_factory=list)
    kitchen_hint: str = ""

    photos: list[str] = field(default_factory=list)
    plan_url: str = ""
    has_3d: bool = False

    # Why a price should not be read as a market price. DVF records every
    # transfer, including bare-ownership sales, transfers between relatives and
    # undivided shares, which produce €/m² an order of magnitude off the market.
    price_flag: str = ""

    stations: list[Station] = field(default_factory=list)
    notes: str = ""

    # ---------------------------------------------------------------- derived

    @property
    def eur_m2(self) -> float | None:
        if self.price and self.surface and self.surface > 0:
            return self.price / self.surface
        return None

    @property
    def nearest(self) -> Station | None:
        routed = [s for s in self.stations if s.walk_m is not None]
        return min(routed, key=lambda s: s.walk_m) if routed else None

    def walk_m_for(self, modes: list[str] | None = None) -> float | None:
        """Shortest walk to a station, optionally restricted to some modes."""
        pool = [s for s in self.stations if s.walk_m is not None]
        if modes:
            wanted = {m.upper() for m in modes}
            pool = [s for s in pool if s.mode.upper() in wanted]
        return min((s.walk_m for s in pool), default=None)

    @property
    def delivery_key(self) -> tuple[int, int] | None:
        if not self.delivery_year:
            return None
        return (self.delivery_year, self.delivery_quarter or 1)

    @property
    def delivery_label(self) -> str:
        if self.delivery_year and self.delivery_quarter:
            return f"T{self.delivery_quarter} {self.delivery_year}"
        return str(self.delivery_year or "")

    @property
    def has_exact_address(self) -> bool:
        return self.address_precision in ("housenumber", "street", "source")

    @property
    def is_market_price(self) -> bool:
        return not self.price_flag

    def as_dict(self) -> dict:
        out = {f.name: getattr(self, f.name) for f in fields(self)}
        out["stations"] = [s.as_dict() for s in self.stations]
        out["eur_m2"] = round(self.eur_m2) if self.eur_m2 else None
        out["delivery_label"] = self.delivery_label
        nearest = self.nearest
        out["nearest_station"] = nearest.as_dict() if nearest else None
        out["has_exact_address"] = self.has_exact_address
        out["has_photos"] = bool(self.photos)
        out["has_plan"] = bool(self.plan_url)
        out["is_market_price"] = self.is_market_price
        return out


# Absolute guard rails. Nothing outside these is a market sale anywhere in
# Île-de-France; DVF simply records every transfer, whatever its terms.
MARKET_EUR_M2_MIN = 900.0
MARKET_EUR_M2_MAX = 40_000.0
MARKET_PRICE_MIN = 15_000.0

# Relative guard rails, applied against the commune's own median. A fixed floor
# cannot serve Paris and Seine-et-Marne at once: 950 €/m² is absurd in
# Val-de-Marne yet unremarkable in parts of Seine-et-Marne.
LOCAL_LOW_RATIO = 0.45
LOCAL_HIGH_RATIO = 2.6
LOCAL_MIN_SAMPLE = 12


def price_plausibility(price: float | None, surface: float | None) -> str:
    """Empty string when the price reads as a market price, else the reason."""
    if not price or not surface or surface <= 0:
        return ""
    if price < MARKET_PRICE_MIN:
        return "prix < 15 k€ (cession, part indivise ou soulte)"
    ratio = price / surface
    if ratio < MARKET_EUR_M2_MIN:
        return f"{ratio:.0f} €/m² anormalement bas (nue-propriété, vente familiale…)"
    if ratio > MARKET_EUR_M2_MAX:
        return f"{ratio:.0f} €/m² anormalement haut (lot multiple ou surface partielle)"
    return ""


def flag_against_local_median(listings: list) -> int:
    """Flag transfers far from their own commune's median €/m².

    Runs after the absolute check, on the survivors, so the median itself is
    not dragged by the very rows it is meant to catch. Communes with too few
    sales keep the absolute rule only — a median over five transactions would
    be noise deciding what counts as normal.
    """
    import statistics

    buckets: dict[str, list[float]] = {}
    for listing in listings:
        if listing.price_flag or not listing.insee:
            continue
        ratio = listing.eur_m2
        if ratio:
            buckets.setdefault(listing.insee, []).append(ratio)

    medians = {
        insee: statistics.median(values)
        for insee, values in buckets.items()
        if len(values) >= LOCAL_MIN_SAMPLE
    }

    flagged = 0
    for listing in listings:
        if listing.price_flag:
            continue
        median = medians.get(listing.insee)
        ratio = listing.eur_m2
        if not median or not ratio:
            continue
        if ratio < median * LOCAL_LOW_RATIO:
            listing.price_flag = (
                f"{ratio:.0f} €/m² très en dessous de la médiane communale "
                f"({median:.0f} €/m²)"
            )
            flagged += 1
        elif ratio > median * LOCAL_HIGH_RATIO:
            listing.price_flag = (
                f"{ratio:.0f} €/m² très au-dessus de la médiane communale "
                f"({median:.0f} €/m²)"
            )
            flagged += 1
    return flagged


def make_id(*parts) -> str:
    raw = "|".join(str(p) for p in parts)
    return hashlib.sha1(raw.encode("utf-8")).hexdigest()[:16]
