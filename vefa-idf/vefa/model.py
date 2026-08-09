"""The record every source is normalised into."""

from __future__ import annotations

import math
import re
from dataclasses import dataclass, field, asdict

IDF_DEPTS = {"75", "77", "78", "91", "92", "93", "94", "95"}

QUARTER_WORDS = {
    "1er": 1, "1e": 1, "1": 1, "premier": 1,
    "2eme": 2, "2ème": 2, "2e": 2, "2": 2, "deuxieme": 2, "second": 2,
    "3eme": 3, "3ème": 3, "3e": 3, "3": 3, "troisieme": 3,
    "4eme": 4, "4ème": 4, "4e": 4, "4": 4, "quatrieme": 4, "dernier": 4,
}


@dataclass
class Program:
    source: str
    url: str
    name: str = ""
    developer: str = ""
    address: str = ""
    city: str = ""
    postcode: str = ""
    insee: str = ""
    dept: str = ""
    lat: float | None = None
    lon: float | None = None

    # Money / surface. ``*_t4`` fields are only set when the source publishes
    # data attributable to the 4-room typology specifically.
    price_program_min: float | None = None
    price_program_max: float | None = None
    price_t4_min: float | None = None
    price_t4_max: float | None = None
    area_program_min: float | None = None
    area_program_max: float | None = None
    area_t4_min: float | None = None
    area_t4_max: float | None = None

    typologies: list[int] = field(default_factory=list)
    delivery_year: int | None = None
    delivery_quarter: int | None = None
    fiscal: list[str] = field(default_factory=list)
    kitchen_hint: str = ""
    plan_url: str = ""   # publicly linked plan, no form involved
    notes: str = ""

    # Filled by the geo stage.
    zone_abc: str = ""
    station_name: str = ""
    station_line: str = ""
    walk_m: float | None = None
    walk_min: float | None = None
    geocode_precision: str = ""

    # The single T4 lot the €/m² is computed from. Price and surface here
    # always come from the same lot, so the ratio describes something real.
    lot_price: float | None = None
    lot_area: float | None = None
    lot_floor: str = ""
    lot_exposure: str = ""
    lot_available: str = ""
    lot_count_t4: int = 0

    def set_best_t4_lot(self, lots: list[dict]) -> None:
        """Pick the T4 lot that best fits the brief: both figures published,
        surface at or above the target, cheapest per m². Falls back to the
        cheapest complete lot when none reaches the target surface."""
        self.lot_count_t4 = len(lots)
        complete = [l for l in lots if l.get("price") and l.get("area")]
        if not complete:
            return
        available = [l for l in complete if l.get("available")] or complete
        big = [l for l in available if l["area"] >= 80.0] or available
        best = min(big, key=lambda l: l["price"] / l["area"])
        self.lot_price = best["price"]
        self.lot_area = best["area"]
        self.lot_floor = str(best.get("floor") or "")
        self.lot_exposure = str(best.get("exposure") or "")
        self.lot_available = "oui" if best.get("available") else "non"

    def has_t4(self) -> bool:
        return 4 in self.typologies

    def price_for_t4(self) -> float | None:
        return self.lot_price if self.lot_price else self.price_t4_min

    def area_for_t4(self) -> float | None:
        return self.lot_area if self.lot_area else self.area_t4_min

    def eur_per_m2(self) -> float | None:
        """Only computed from a matched price/surface pair on one lot."""
        if self.lot_price and self.lot_area and self.lot_area > 0:
            return self.lot_price / self.lot_area
        return None

    def delivery_label(self) -> str:
        if self.delivery_year and self.delivery_quarter:
            return f"T{self.delivery_quarter} {self.delivery_year}"
        if self.delivery_year:
            return str(self.delivery_year)
        return ""

    def as_dict(self) -> dict:
        d = asdict(self)
        d["typologies"] = "/".join(str(t) for t in sorted(set(self.typologies)))
        d["fiscal"] = "/".join(sorted(set(self.fiscal)))
        d["delivery"] = self.delivery_label()
        eur = self.eur_per_m2()
        d["eur_per_m2"] = round(eur) if eur else None
        return d


# --------------------------------------------------------------------------
# Small shared parsing helpers
# --------------------------------------------------------------------------

def clean_number(text: str) -> float | None:
    """Parse a French-formatted number ('319 243', '82,19')."""
    if text is None:
        return None
    s = str(text).replace(" ", " ").replace("\xa0", " ").strip()
    s = re.sub(r"[^\d,.\s]", "", s)
    s = s.replace(" ", "")
    if "," in s and "." in s:
        s = s.replace(".", "").replace(",", ".")
    elif "," in s:
        s = s.replace(",", ".")
    try:
        value = float(s)
    except ValueError:
        return None
    return value if math.isfinite(value) else None


def parse_quarter(text: str) -> tuple[int | None, int | None]:
    """Extract (quarter, year) from strings like '2ème trimestre 2027'."""
    if not text:
        return None, None
    # Kaufman & Broad writes "1ᵉʳ trim. 2028" with superscript letters, and
    # several sites use narrow no-break spaces around the ordinal.
    low = text.lower()
    for src_ch, dst in (
        ("\xa0", " "), (" ", " "), (" ", " "),
        ("ᵉʳ", "er"), ("ᵉ", "e"), ("ʳ", "r"), ("ᵈ", "d"), ("ᵗ", "t"),
    ):
        low = low.replace(src_ch, dst)
    # Sites write this as "2ème trimestre 2027", "3e trim. 2028" or "4e T 2029".
    m = re.search(
        r"(1er|1e|2ème|2eme|2e|3ème|3eme|3e|4ème|4eme|4e|premier|deuxi[eè]me"
        r"|troisi[eè]me|quatri[eè]me|dernier|\d)\s*(?:er|e|ème|eme)?\s*"
        r"trim(?:estre|\.|\b)\s*(\d{4})",
        low,
    )
    if m:
        token = m.group(1).replace("è", "e")
        quarter = QUARTER_WORDS.get(token)
        return quarter, int(m.group(2))
    m = re.search(r"\bt([1-4])\s*[-/ ]?\s*(20\d{2})\b", low)
    if m:
        return int(m.group(1)), int(m.group(2))
    m = re.search(r"livraison[^\d]{0,20}(20\d{2})", low)
    if m:
        return None, int(m.group(1))
    return None, None


def quarter_from_iso(date_str: str) -> tuple[int | None, int | None]:
    m = re.match(r"(\d{4})-(\d{2})", str(date_str or ""))
    if not m:
        return None, None
    year, month = int(m.group(1)), int(m.group(2))
    return (month - 1) // 3 + 1, year


FISCAL_PATTERNS = {
    "PTZ": r"\bptz\b|pr[eê]t\s+[àa]\s+taux\s+z[ée]ro",
    "TVA réduite": r"tva\s*(?:r[ée]duite|[àa]?\s*5[,.]5|[àa]?\s*7\s*%)",
    "Jeanbrun": r"\bjeanbrun\b",
    "LMNP": r"\blmnp\b",
    "LLI": r"\blli\b",
    "BRS": r"\bbrs\b|bail\s+r[ée]el\s+solidaire",
    "ANRU": r"\banru\b",
    "Pinel": r"\bpinel\b",
}


def detect_fiscal(text: str) -> list[str]:
    low = (text or "").lower()
    return [label for label, pattern in FISCAL_PATTERNS.items() if re.search(pattern, low)]


KITCHEN_PATTERNS = {
    "cuisine séparée": r"cuisine\s+(?:s[ée]par[ée]e|ferm[ée]e|ind[ée]pendante)",
    "TMA / plan configurable": (
        r"\btma\b|travaux\s+modificatifs?\s+(?:de\s+l['’]?)?acqu[ée]reur"
        r"|plan\s+(?:configurable|modulable|[àa]\s+la\s+carte)"
        r"|appartement\s+(?:configurable|modulable)|personnalis(?:er|ation)\s+(?:votre|des?)\s+(?:plan|logement|int[ée]rieur)"
    ),
    "cuisine ouverte (à cloisonner)": r"cuisine\s+(?:ouverte|am[ée]ricaine)",
}


def detect_kitchen(text: str) -> str:
    low = (text or "").lower()
    hits = [label for label, pattern in KITCHEN_PATTERNS.items() if re.search(pattern, low)]
    return " / ".join(hits)
