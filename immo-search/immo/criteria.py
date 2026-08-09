"""Search criteria: parsing, validation, and the per-listing predicate.

Criteria arrive as untyped strings (query string, CLI flags, JSON body). They
are parsed once here, into typed fields, and every bad value raises
:class:`CriteriaError` instead of silently degrading into "no filter" — a
misspelt bound that quietly widens the search is worse than an error message.

Unknown-vs-excluded: when a listing does not publish the field a filter targets,
it is dropped by default. Set ``keep_unknown=True`` to keep those rows instead,
which is what you want while exploring a thin dataset.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field, fields
from datetime import date

from .model import KIND_ANCIEN, KIND_NEUF, Listing, slugify

MODES = ["RER", "METRO", "TRAIN", "TRAM"]
SORTS = {
    "eur_m2": lambda l: (l.eur_m2 is None, l.eur_m2 or 0),
    "price": lambda l: (l.price is None, l.price or 0),
    "surface": lambda l: (l.surface is None, -(l.surface or 0)),
    "rooms": lambda l: (l.rooms is None, -(l.rooms or 0)),
    "walk": lambda l: (l.walk_m_for() is None, l.walk_m_for() or 0),
    "delivery": lambda l: (l.delivery_key is None, l.delivery_key or (0, 0)),
    "date": lambda l: (not l.sale_date, l.sale_date or ""),
}


class CriteriaError(ValueError):
    """A criterion could not be understood."""


def _num(value, name: str, minimum=None, maximum=None) -> float | None:
    if value in (None, "", []):
        return None
    if isinstance(value, (list, tuple)):
        value = value[0]
    try:
        out = float(str(value).replace(" ", "").replace(",", "."))
    except ValueError:
        raise CriteriaError(f"{name}: '{value}' n'est pas un nombre")
    if minimum is not None and out < minimum:
        raise CriteriaError(f"{name}: doit être ≥ {minimum}")
    if maximum is not None and out > maximum:
        raise CriteriaError(f"{name}: doit être ≤ {maximum}")
    return out


def _int(value, name: str, minimum=None, maximum=None) -> int | None:
    out = _num(value, name, minimum, maximum)
    return int(out) if out is not None else None


def _bool(value, name: str) -> bool | None:
    if value in (None, "", []):
        return None
    if isinstance(value, (list, tuple)):
        value = value[0]
    text = str(value).strip().lower()
    if text in ("1", "true", "oui", "yes", "on"):
        return True
    if text in ("0", "false", "non", "no", "off"):
        return False
    raise CriteriaError(f"{name}: '{value}' n'est pas un booléen")


def _list(value) -> list[str]:
    if value in (None, "", []):
        return []
    if isinstance(value, str):
        value = value.split(",")
    out = []
    for item in value:
        for piece in str(item).split(","):
            piece = piece.strip()
            if piece:
                out.append(piece)
    return out


def _quarter_bound(value, name: str) -> tuple[int, int] | None:
    """Accept '2027', 'T4 2027', '2027-T4', '2027Q4'."""
    if value in (None, "", []):
        return None
    if isinstance(value, (list, tuple)):
        value = value[0]
    text = str(value).strip().upper().replace("-", " ")
    m = re.match(r"^(20\d{2})$", text)
    if m:
        return (int(m.group(1)), 0)
    m = re.match(r"^T([1-4])\s*(20\d{2})$", text) or re.match(r"^(20\d{2})\s*[TQ]([1-4])$", text)
    if m:
        a, b = m.group(1), m.group(2)
        year, quarter = (int(b), int(a)) if len(a) == 1 else (int(a), int(b))
        return (year, quarter)
    raise CriteriaError(f"{name}: '{value}' n'est pas un trimestre (ex. 'T4 2027' ou '2027')")


@dataclass
class Criteria:
    # what to search
    kinds: list[str] = field(default_factory=list)      # neuf / ancien
    q: str = ""
    sources: list[str] = field(default_factory=list)
    developers: list[str] = field(default_factory=list)

    # where
    depts: list[str] = field(default_factory=list)
    cities: list[str] = field(default_factory=list)
    zones: list[str] = field(default_factory=list)

    # the flat
    rooms_min: int | None = None
    rooms_max: int | None = None
    surface_min: float | None = None
    surface_max: float | None = None
    price_min: float | None = None
    price_max: float | None = None
    eur_m2_min: float | None = None
    eur_m2_max: float | None = None
    floor_min: int | None = None
    floor_max: int | None = None
    exposures: list[str] = field(default_factory=list)

    # timing
    delivery_from: tuple[int, int] | None = None
    delivery_to: tuple[int, int] | None = None
    sold_after: str = ""
    sold_before: str = ""

    # transport. ``walk_*`` needs a routed pedestrian distance, which only the
    # marketed programmes carry; ``crow_max_m`` works on everything because it
    # is computed locally. A walk is never shorter than the straight line, so
    # a crow bound is a sound pre-filter for a walking requirement.
    walk_max_m: float | None = None
    walk_max_min: float | None = None
    crow_max_m: float | None = None
    modes: list[str] = field(default_factory=list)
    lines: list[str] = field(default_factory=list)

    # qualifiers
    fiscal: list[str] = field(default_factory=list)
    features: list[str] = field(default_factory=list)
    kitchen: str = ""                     # separee | cloisonnable | any
    only_available: bool | None = None
    with_photos: bool | None = None
    with_plan: bool | None = None
    with_exact_address: bool | None = None
    carrez_only: bool | None = None

    # behaviour
    include_atypical: bool = False   # DVF transfers that are not market sales
    keep_unknown: bool = False
    sort: str = "eur_m2"
    order: str = "asc"
    page: int = 1
    per_page: int = 25

    # ------------------------------------------------------------------ parse

    @classmethod
    def from_params(cls, params: dict) -> "Criteria":
        """Build from a mapping of str -> str|list[str] (query string or JSON)."""
        get = params.get
        c = cls(
            kinds=[k.lower() for k in _list(get("kind"))],
            q=(_list(get("q")) or [""])[0].strip(),
            sources=_list(get("source")),
            developers=_list(get("developer")),
            depts=_list(get("dept")),
            cities=[slugify(x) for x in _list(get("city"))],
            zones=[x.replace(" ", "").lower() for x in _list(get("zone"))],
            rooms_min=_int(get("rooms_min"), "rooms_min", 1, 20),
            rooms_max=_int(get("rooms_max"), "rooms_max", 1, 20),
            surface_min=_num(get("surface_min"), "surface_min", 0, 10_000),
            surface_max=_num(get("surface_max"), "surface_max", 0, 10_000),
            price_min=_num(get("price_min"), "price_min", 0, 100_000_000),
            price_max=_num(get("price_max"), "price_max", 0, 100_000_000),
            eur_m2_min=_num(get("eur_m2_min"), "eur_m2_min", 0, 100_000),
            eur_m2_max=_num(get("eur_m2_max"), "eur_m2_max", 0, 100_000),
            floor_min=_int(get("floor_min"), "floor_min", -3, 60),
            floor_max=_int(get("floor_max"), "floor_max", -3, 60),
            exposures=[x.upper() for x in _list(get("exposure"))],
            delivery_from=_quarter_bound(get("delivery_from"), "delivery_from"),
            delivery_to=_quarter_bound(get("delivery_to"), "delivery_to"),
            sold_after=(_list(get("sold_after")) or [""])[0],
            sold_before=(_list(get("sold_before")) or [""])[0],
            walk_max_m=_num(get("walk_max_m"), "walk_max_m", 0, 20_000),
            walk_max_min=_num(get("walk_max_min"), "walk_max_min", 0, 300),
            crow_max_m=_num(get("crow_max_m"), "crow_max_m", 0, 50_000),
            modes=[m.upper() for m in _list(get("mode"))],
            lines=[l.upper() for l in _list(get("line"))],
            fiscal=_list(get("fiscal")),
            features=[f.lower() for f in _list(get("feature"))],
            kitchen=(_list(get("kitchen")) or [""])[0].lower(),
            only_available=_bool(get("only_available"), "only_available"),
            with_photos=_bool(get("with_photos"), "with_photos"),
            with_plan=_bool(get("with_plan"), "with_plan"),
            with_exact_address=_bool(get("with_exact_address"), "with_exact_address"),
            carrez_only=_bool(get("carrez_only"), "carrez_only"),
            include_atypical=_bool(get("include_atypical"), "include_atypical") or False,
            keep_unknown=_bool(get("keep_unknown"), "keep_unknown") or False,
            sort=(_list(get("sort")) or ["eur_m2"])[0],
            order=(_list(get("order")) or ["asc"])[0].lower(),
            page=_int(get("page"), "page", 1, 100_000) or 1,
            per_page=_int(get("per_page"), "per_page", 1, 200) or 25,
        )
        c.validate()
        return c

    def validate(self) -> None:
        for kind in self.kinds:
            if kind not in (KIND_NEUF, KIND_ANCIEN):
                raise CriteriaError(f"kind: '{kind}' inconnu (neuf|ancien)")
        if self.sort not in SORTS:
            raise CriteriaError(f"sort: '{self.sort}' inconnu ({'|'.join(SORTS)})")
        if self.order not in ("asc", "desc"):
            raise CriteriaError("order: asc|desc attendu")
        for mode in self.modes:
            if mode not in MODES:
                raise CriteriaError(f"mode: '{mode}' inconnu ({'|'.join(MODES)})")
        if self.kitchen and self.kitchen not in ("separee", "cloisonnable", "any"):
            raise CriteriaError("kitchen: separee|cloisonnable|any attendu")
        for lo, hi, label in (
            (self.rooms_min, self.rooms_max, "rooms"),
            (self.surface_min, self.surface_max, "surface"),
            (self.price_min, self.price_max, "price"),
            (self.eur_m2_min, self.eur_m2_max, "eur_m2"),
            (self.floor_min, self.floor_max, "floor"),
        ):
            if lo is not None and hi is not None and lo > hi:
                raise CriteriaError(f"{label}: le minimum dépasse le maximum")
        if self.delivery_from and self.delivery_to and self.delivery_from > self.delivery_to:
            raise CriteriaError("delivery: la borne basse dépasse la borne haute")
        for value, label in ((self.sold_after, "sold_after"), (self.sold_before, "sold_before")):
            if value and not re.match(r"^\d{4}-\d{2}-\d{2}$", value):
                raise CriteriaError(f"{label}: date AAAA-MM-JJ attendue")

    def as_dict(self) -> dict:
        return {f.name: getattr(self, f.name) for f in fields(self)}


# --------------------------------------------------------------------------
# Matching
# --------------------------------------------------------------------------

def _range_ok(value, lo, hi, keep_unknown: bool) -> bool:
    if value is None:
        return keep_unknown if (lo is not None or hi is not None) else True
    if lo is not None and value < lo:
        return False
    if hi is not None and value > hi:
        return False
    return True


def _floor_number(raw: str) -> int | None:
    text = (raw or "").strip().lower()
    if not text:
        return None
    if text in ("rdc", "rez-de-chaussée", "rez de chaussee", "0"):
        return 0
    m = re.search(r"-?\d+", text)
    return int(m.group(0)) if m else None


def matches(listing: Listing, c: Criteria) -> bool:
    ku = c.keep_unknown

    # Non-market transfers are excluded by default. Left in, they dominate the
    # cheapest-first ranking and drag every median down: DVF records
    # bare-ownership sales and transfers between relatives alongside real ones.
    if listing.price_flag and not c.include_atypical:
        return False
    if c.kinds and listing.kind not in c.kinds:
        return False
    if c.sources and listing.source not in c.sources:
        return False
    if c.developers:
        wanted = {slugify(d) for d in c.developers}
        if slugify(listing.developer) not in wanted:
            return False
    if c.depts and (listing.dept or "") not in c.depts:
        return False
    if c.cities and slugify(listing.city) not in c.cities:
        return False
    if c.zones:
        zone = (listing.zone_abc or "").replace(" ", "").lower()
        if not zone:
            if not ku:
                return False
        elif zone not in c.zones:
            return False

    if c.q:
        haystack = " ".join(
            [listing.name, listing.city, listing.address, listing.developer, listing.postcode]
        ).lower()
        for token in c.q.lower().split():
            if token not in haystack:
                return False

    if not _range_ok(listing.rooms, c.rooms_min, c.rooms_max, ku):
        return False
    if not _range_ok(listing.surface, c.surface_min, c.surface_max, ku):
        return False
    if not _range_ok(listing.price, c.price_min, c.price_max, ku):
        return False
    if not _range_ok(listing.eur_m2, c.eur_m2_min, c.eur_m2_max, ku):
        return False
    if c.floor_min is not None or c.floor_max is not None:
        if not _range_ok(_floor_number(listing.floor), c.floor_min, c.floor_max, ku):
            return False
    if c.exposures:
        exposure = (listing.exposure or "").upper()
        if not exposure:
            if not ku:
                return False
        elif not any(e in exposure for e in c.exposures):
            return False

    if c.delivery_from or c.delivery_to:
        key = listing.delivery_key
        if key is None:
            if not ku:
                return False
        else:
            if c.delivery_from and key < c.delivery_from:
                return False
            if c.delivery_to and key > (c.delivery_to[0], c.delivery_to[1] or 4):
                return False
    if c.sold_after and (not listing.sale_date or listing.sale_date < c.sold_after):
        return False
    if c.sold_before and (not listing.sale_date or listing.sale_date > c.sold_before):
        return False

    wants_transport = (
        c.walk_max_m is not None or c.walk_max_min is not None
        or c.crow_max_m is not None or c.modes or c.lines
    )
    if wants_transport:
        pool = list(listing.stations)
        if c.modes:
            pool = [s for s in pool if s.mode.upper() in c.modes]
        if c.lines:
            pool = [
                s for s in pool
                if any(line in (s.line or "").upper() for line in c.lines)
            ]
        if c.crow_max_m is not None:
            pool = [s for s in pool if s.crow_m is not None and s.crow_m <= c.crow_max_m]
        if c.walk_max_m is not None or c.walk_max_min is not None:
            routed = [s for s in pool if s.walk_m is not None]
            if not routed and pool:
                # Distance on foot was never measured for this listing. Saying
                # "no" would hide it and saying "yes" would assert a distance we
                # never computed, so honour keep_unknown instead of guessing.
                if not ku:
                    return False
                routed = []
            pool = routed
            if c.walk_max_m is not None:
                pool = [s for s in pool if s.walk_m <= c.walk_max_m]
            if c.walk_max_min is not None:
                pool = [s for s in pool if (s.walk_min or 1e9) <= c.walk_max_min]
            if not pool and not ku:
                return False
        elif not pool:
            return False

    if c.fiscal:
        have = {f.lower() for f in listing.fiscal}
        if not all(any(w.lower() in h for h in have) for w in c.fiscal):
            return False
    if c.features:
        have = {f.lower() for f in listing.features}
        if not set(c.features) <= have:
            return False
    if c.kitchen:
        hint = (listing.kitchen_hint or "").lower()
        if c.kitchen == "separee" and "séparée" not in hint:
            return False
        if c.kitchen == "cloisonnable" and "tma" not in hint and "configurable" not in hint:
            return False
        if c.kitchen == "any" and not hint:
            return False

    if c.only_available and listing.available is False:
        return False
    if c.with_photos and not listing.photos:
        return False
    if c.with_plan and not listing.plan_url:
        return False
    if c.with_exact_address and not listing.has_exact_address:
        return False
    if c.carrez_only and not listing.surface_is_carrez:
        return False
    return True
