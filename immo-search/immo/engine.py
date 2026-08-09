"""Search engine: filter, sort, paginate, and describe the result set.

Facets are computed on the listings that match *every other* criterion but not
the facet's own field. That is what makes a facet count usable: picking
"Val-de-Marne" from the department facet returns exactly the number the facet
promised, instead of the number you would get if the current department filter
were also applied to itself.
"""

from __future__ import annotations

import statistics
from dataclasses import replace

from .criteria import SORTS, Criteria, matches
from .model import Listing, slugify

FACET_FIELDS = ["kind", "dept", "city", "zone_abc", "source", "developer", "fiscal", "rooms"]


def _facet_values(listing: Listing, name: str) -> list[str]:
    if name == "fiscal":
        return list(listing.fiscal)
    if name == "rooms":
        return [str(listing.rooms)] if listing.rooms else []
    value = getattr(listing, name, "") or ""
    return [str(value)] if value else []


def _without(c: Criteria, name: str) -> Criteria:
    """A copy of the criteria with the filter driving ``name`` cleared."""
    clear = {
        "kind": {"kinds": []},
        "dept": {"depts": []},
        "city": {"cities": []},
        "zone_abc": {"zones": []},
        "source": {"sources": []},
        "developer": {"developers": []},
        "fiscal": {"fiscal": []},
        "rooms": {"rooms_min": None, "rooms_max": None},
    }[name]
    return replace(c, **clear)


class Index:
    """An in-memory index over listings. Cheap to build, fast enough to scan."""

    def __init__(self, listings: list[Listing]) -> None:
        self.listings = listings
        self.by_id = {l.id: l for l in listings}

    def __len__(self) -> int:
        return len(self.listings)

    # ---------------------------------------------------------------- search

    def search(self, c: Criteria, with_facets: bool = True) -> dict:
        hits = [l for l in self.listings if matches(l, c)]
        hits.sort(key=SORTS[c.sort], reverse=(c.order == "desc"))

        total = len(hits)
        pages = max(1, (total + c.per_page - 1) // c.per_page)
        page = min(c.page, pages)
        start = (page - 1) * c.per_page
        window = hits[start: start + c.per_page]

        out = {
            "total": total,
            "page": page,
            "pages": pages,
            "per_page": c.per_page,
            "results": [l.as_dict() for l in window],
            "stats": self.stats(hits),
        }
        if with_facets:
            out["facets"] = self.facets(c)
        return out

    # ---------------------------------------------------------------- facets

    def facets(self, c: Criteria, limit: int = 40) -> dict:
        out: dict[str, list[dict]] = {}
        for name in FACET_FIELDS:
            base = _without(c, name)
            counts: dict[str, int] = {}
            for listing in self.listings:
                if not matches(listing, base):
                    continue
                for value in _facet_values(listing, name):
                    counts[value] = counts.get(value, 0) + 1
            ordered = sorted(counts.items(), key=lambda kv: (-kv[1], kv[0]))[:limit]
            out[name] = [
                {"value": v, "count": n, "slug": slugify(v)} for v, n in ordered
            ]
        return out

    # ----------------------------------------------------------------- stats

    @staticmethod
    def stats(listings: list[Listing]) -> dict:
        def describe(values: list[float]) -> dict | None:
            values = [v for v in values if v is not None]
            if not values:
                return None
            values.sort()
            return {
                "count": len(values),
                "min": round(values[0], 1),
                "max": round(values[-1], 1),
                "median": round(statistics.median(values), 1),
                "mean": round(statistics.fmean(values), 1),
            }

        return {
            "eur_m2": describe([l.eur_m2 for l in listings]),
            "price": describe([l.price for l in listings]),
            "surface": describe([l.surface for l in listings]),
            "walk_m": describe([l.walk_m_for() for l in listings]),
            "by_kind": {
                kind: sum(1 for l in listings if l.kind == kind)
                for kind in sorted({l.kind for l in listings})
            },
        }

    # ------------------------------------------------------------ comparables

    def comparables(
        self, listing: Listing, radius_m: float = 1500, limit: int = 12
    ) -> list[dict]:
        """Nearby completed sales of a similar flat — the price reality check.

        Compares against DVF transactions only: an asking price next to another
        asking price says nothing about what the market settles at.
        """
        from .geo import haversine_m

        if listing.lat is None:
            return []
        out = []
        for other in self.listings:
            if other.kind != "ancien" or other.lat is None or other.id == listing.id:
                continue
            if listing.rooms and other.rooms and abs(other.rooms - listing.rooms) > 1:
                continue
            distance = haversine_m(listing.lat, listing.lon, other.lat, other.lon)
            if distance > radius_m:
                continue
            out.append((distance, other))
        out.sort(key=lambda pair: pair[0])
        results = []
        for distance, other in out[:limit]:
            row = other.as_dict()
            row["distance_m"] = round(distance)
            results.append(row)
        return results
