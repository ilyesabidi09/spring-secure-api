"""Persisting and reloading the index."""

from __future__ import annotations

import json
import sys
from dataclasses import fields
from pathlib import Path

from .model import Listing, Station

# "python3" does not exist on a default Windows install; the launcher is "py".
PY = "py" if sys.platform == "win32" else "python3"

_LISTING_FIELDS = {f.name for f in fields(Listing)}
_STATION_FIELDS = {f.name for f in fields(Station)}


def listing_from_dict(row: dict) -> Listing:
    """Rebuild a Listing, ignoring the derived keys ``as_dict`` adds."""
    kwargs = {k: v for k, v in row.items() if k in _LISTING_FIELDS and k != "stations"}
    kwargs.setdefault("id", "")
    kwargs.setdefault("kind", "neuf")
    kwargs.setdefault("source", "")
    listing = Listing(**kwargs)
    listing.stations = [
        Station(**{k: v for k, v in s.items() if k in _STATION_FIELDS})
        for s in (row.get("stations") or [])
    ]
    return listing


def load_index(path: Path) -> tuple[list[Listing], dict]:
    path = Path(path)
    if not path.exists():
        raise FileNotFoundError(
            f"{path} absent.\n"
            f"L'index se construit une fois avant toute recherche :\n"
            f"    {PY} build_index.py --dvf-depts 94 93 --dvf-years 2024"
        )
    payload = json.loads(path.read_text(encoding="utf-8"))
    listings = [listing_from_dict(row) for row in payload.get("listings", [])]
    meta = {k: v for k, v in payload.items() if k != "listings"}
    return listings, meta
