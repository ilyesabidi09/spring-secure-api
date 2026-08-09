"""Per-site discovery and extraction.

Every source exposes ``discover(ctx) -> list[str]`` and
``parse(ctx, url, html) -> list[Program]``. Discovery starts from the sitemaps
declared in each site's robots.txt, so we only ever walk URLs the site itself
publishes for crawling.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from .model import (
    IDF_DEPTS,
    Program,
    clean_number,
    detect_fiscal,
    parse_quarter,
    quarter_from_iso,
)
from .parsing import NuxtPayload, json_ld_of_type, links, to_text


@dataclass
class Context:
    fetcher: object
    limit_pages: int = 0  # 0 = no limit


def _sitemap_locs(xml: str) -> list[str]:
    return re.findall(r"<loc>\s*([^<\s]+)\s*</loc>", xml or "")


def _is_idf_dept(code: str) -> bool:
    return str(code).zfill(2)[:2] in IDF_DEPTS


# ---------------------------------------------------------------------------
# explorimmoneuf (Figaro Immoneuf) — richest source: the SSR payload carries
# per-typology prices, coordinates, developer and delivery date.
# ---------------------------------------------------------------------------

class Explorimmoneuf:
    name = "explorimmoneuf"
    base = "https://www.explorimmoneuf.com"
    sitemaps = [
        f"{base}/sitemap/fi9/sitemap-programme-4pieces.xml",
        f"{base}/sitemap/fi9/sitemap-programme.xml",
    ]

    def discover(self, ctx: Context) -> list[str]:
        listing: list[str] = []
        for sm in self.sitemaps:
            xml = ctx.fetcher.get(sm)
            for url in _sitemap_locs(xml):
                m = re.search(r"-(\d{2})-promoteur", url)
                if m and _is_idf_dept(m.group(1)):
                    listing.append(url)
        listing = sorted(set(listing))

        detail: list[str] = []
        for url in listing:
            html = ctx.fetcher.get(url)
            if not html:
                continue
            detail.extend(links(html, r"/programme/detail-\d+", self.base))
        return sorted(set(detail))

    def parse(self, ctx: Context, url: str, html: str) -> list[Program]:
        payload = NuxtPayload.from_html(html)
        if not payload:
            return []
        candidates = payload.objects_with("programName", "location")
        if not candidates:
            return []
        # The page's own program is the one carrying accommodations.
        node = max(
            candidates,
            key=lambda n: len(n.get("accommodations") or []),
        )

        loc = node.get("location") or {}
        coords = loc.get("coordinates") or {}
        text = to_text(html)

        prog = Program(source=self.name, url=url)
        prog.name = (node.get("programName") or node.get("name") or "").strip()
        prog.developer = ((node.get("advertiser") or {}).get("name") or "").strip()
        prog.address = (loc.get("address") or "").strip()
        prog.city = (loc.get("city") or "").strip()
        prog.postcode = str(loc.get("postalCode") or "").strip()
        prog.insee = str(loc.get("inseeCode") or "").strip()
        prog.dept = str(loc.get("departmentCode") or "").strip()
        if coords.get("lat"):
            prog.lat, prog.lon = coords.get("lat"), coords.get("lon")

        prog.price_program_min = (node.get("priceMin") or 0) or None
        prog.price_program_max = (node.get("priceMax") or 0) or None
        prog.area_program_min = (node.get("areaMin") or 0) or None
        prog.area_program_max = (node.get("areaMax") or 0) or None

        delivery = node.get("delivery") or {}
        prog.delivery_quarter, prog.delivery_year = quarter_from_iso(delivery.get("date"))

        laws = node.get("investmentLaws") or []
        prog.fiscal = detect_fiscal(" ".join(map(str, laws)) + " " + text[:6000])

        for acc in node.get("accommodations") or []:
            rooms = acc.get("roomCount")
            if not rooms:
                continue
            prog.typologies.append(int(rooms))
            if int(rooms) != 4:
                continue
            price = (acc.get("priceMin") or acc.get("price") or 0) or None
            area = (acc.get("area") or acc.get("areaMin") or 0) or None
            if price:
                prog.price_t4_min = min(filter(None, [prog.price_t4_min, price]))
            hi = (acc.get("priceMax") or 0) or None
            if hi:
                prog.price_t4_max = max(filter(None, [prog.price_t4_max or 0, hi]))
            if area:
                prog.area_t4_min = min(filter(None, [prog.area_t4_min, area]))
            hi_area = (acc.get("areaMax") or 0) or None
            if hi_area:
                prog.area_t4_max = max(filter(None, [prog.area_t4_max or 0, hi_area]))

        if not prog.typologies:
            lo, hi = node.get("roomCountMin") or 0, node.get("roomCountMax") or 0
            if lo and hi:
                prog.typologies = list(range(int(lo), int(hi) + 1))
        return [prog] if prog.name else []


# ---------------------------------------------------------------------------
# Bouygues Immobilier
# ---------------------------------------------------------------------------

class Bouygues:
    name = "bouygues"
    base = "https://www.bouygues-immobilier.com"
    dept_slugs = {
        "paris": "75", "seine-et-marne": "77", "yvelines": "78", "essonne": "91",
        "hauts-de-seine": "92", "seine-saint-denis": "93", "val-de-marne": "94",
        "val-d-oise": "95",
    }

    def discover(self, ctx: Context) -> list[str]:
        city_urls: list[str] = []
        for page in (1, 2):
            xml = ctx.fetcher.get(f"{self.base}/sitemap.xml?page={page}")
            for url in _sitemap_locs(xml):
                m = re.match(rf"{re.escape(self.base)}/([a-z0-9\-]+)/([a-z0-9\-]+)$", url)
                if m and m.group(1) in self.dept_slugs:
                    city_urls.append(url)
        city_urls = sorted(set(city_urls))

        programs: list[str] = []
        for url in city_urls:
            html = ctx.fetcher.get(url)
            if not html:
                continue
            programs.extend(links(html, r"/programme-neuf-[a-z0-9\-]+/ref/\d+", self.base))
        return sorted(set(programs))

    def parse(self, ctx: Context, url: str, html: str) -> list[Program]:
        text = to_text(html)
        product = json_ld_of_type(html, "Product") or {}
        offers = product.get("offers") or {}

        prog = Program(source=self.name, url=url, developer="Bouygues Immobilier")
        raw_name = product.get("name") or ""
        m = re.search(r"neuf\s+(.+?)\s*:\s*(.+)$", raw_name)
        if m:
            prog.name, prog.city = m.group(1).strip(), m.group(2).strip()
        else:
            prog.name = raw_name.strip()

        prog.price_program_min = clean_number(offers.get("lowPrice"))
        prog.price_program_max = clean_number(offers.get("highPrice"))

        # "AVENUE MARIE CURIE 77600 Bussy-Saint-Georges"
        m = re.search(r"([0-9A-ZÀ-Ü' \-]{6,60})\s(\d{5})\s([A-Za-zÀ-ÿ' \-]{3,40})", text)
        if m:
            prog.address = m.group(1).strip()
            prog.postcode = m.group(2)
            prog.city = prog.city or m.group(3).strip()
        else:
            m = re.search(r"\b(\d{5})\b", text)
            if m:
                prog.postcode = m.group(1)
        if prog.postcode:
            prog.dept = prog.postcode[:2]

        prog.delivery_quarter, prog.delivery_year = parse_quarter(text)
        prog.fiscal = detect_fiscal(text[:8000])
        prog.typologies = _typologies_from_text(text)
        prog.notes = "prix = fourchette programme (lots non publics : /ajax/get_program_lots/ interdit par robots.txt)"
        return [prog] if prog.name else []


# ---------------------------------------------------------------------------
# Kaufman & Broad — publishes exact coordinates in JSON-LD.
# ---------------------------------------------------------------------------

class KaufmanBroad:
    name = "kaufman-broad"
    base = "https://www.kaufmanbroad.fr"

    def discover(self, ctx: Context) -> list[str]:
        xml = ctx.fetcher.get(f"{self.base}/sitemap.xml")
        out = []
        for url in _sitemap_locs(xml):
            if "/ile-de-france/" in url and "/programme/" in url:
                out.append(url)
        return sorted(set(out))

    def parse(self, ctx: Context, url: str, html: str) -> list[Program]:
        node = json_ld_of_type(html, "HousingComplex", "Residence", "Product") or {}
        text = to_text(html)
        prog = Program(source=self.name, url=url, developer="Kaufman & Broad")
        prog.name = (node.get("name") or "").strip()

        addr = node.get("address") or {}
        prog.address = (addr.get("streetAddress") or "").strip()
        prog.city = (addr.get("addressLocality") or "").strip()
        prog.postcode = str(addr.get("postalCode") or "").strip()
        prog.dept = prog.postcode[:2] if prog.postcode else str(addr.get("addressRegion") or "")

        geo = node.get("geo") or {}
        if geo.get("latitude"):
            prog.lat = float(geo["latitude"])
            prog.lon = float(geo["longitude"])

        m = re.search(r"[ÀA]\s*partir\s*de\s*([\d\s  ]{5,12})\s*€", text)
        if m:
            prog.price_program_min = clean_number(m.group(1))
        prog.delivery_quarter, prog.delivery_year = parse_quarter(text)
        prog.fiscal = detect_fiscal(text[:8000])
        prog.typologies = _typologies_from_text(text)
        prog.plan_url = _public_plan_link(html)
        return [prog] if prog.name else []


# ---------------------------------------------------------------------------
# Sogeprom
# ---------------------------------------------------------------------------

class Sogeprom:
    name = "sogeprom"
    base = "https://www.sogeprom.fr"

    def discover(self, ctx: Context) -> list[str]:
        xml = ctx.fetcher.get(f"{self.base}/program-sitemap.xml")
        return sorted(
            {u for u in _sitemap_locs(xml) if "/residences/ile-de-france/" in u}
        )

    def parse(self, ctx: Context, url: str, html: str) -> list[Program]:
        text = to_text(html)
        node = json_ld_of_type(html, "Product") or {}
        prog = Program(source=self.name, url=url, developer="Sogeprom")
        prog.name = (node.get("name") or "").strip()
        if not prog.name:
            m = re.search(r"<h1[^>]*>(.*?)</h1>", html, re.S | re.I)
            prog.name = to_text(m.group(1)) if m else ""

        m = re.search(r"\b(\d{5})\b", text)
        if m:
            prog.postcode = m.group(1)
            prog.dept = prog.postcode[:2]
        m = re.search(r"([A-ZÀ-Ü][A-Za-zÀ-ÿ'\- ]{2,35})\s+(75|77|78|91|92|93|94|95)\b", text)
        if m:
            prog.city = m.group(1).strip()
            prog.dept = prog.dept or m.group(2)

        m = re.search(r"[àa]\s*partir\s*de\s*([\d\s  ]{5,12})\s*€", text, re.I)
        if m:
            prog.price_program_min = clean_number(m.group(1))
        prog.delivery_quarter, prog.delivery_year = parse_quarter(text)
        prog.fiscal = detect_fiscal(text[:8000])
        prog.typologies = _typologies_from_text(text)
        return [prog] if prog.name else []


# ---------------------------------------------------------------------------
# Nexity
# ---------------------------------------------------------------------------

class Nexity:
    name = "nexity"
    base = "https://www.nexity.fr"
    idf_slugs = [
        "ile-de-france", "paris", "seine-et-marne", "yvelines", "essonne",
        "hauts-de-seine", "seine-saint-denis", "val-de-marne", "val-d-oise",
    ]

    def discover(self, ctx: Context) -> list[str]:
        xml = ctx.fetcher.get(f"{self.base}/sitemap-achat-vente-neuf.xml")
        out = []
        for url in _sitemap_locs(xml):
            tail = url.rstrip("/").rsplit("/", 1)[-1]
            if tail in self.idf_slugs:
                out.append(url)
        return sorted(set(out))

    def parse(self, ctx: Context, url: str, html: str) -> list[Program]:
        out: list[Program] = []
        # Cards read: "CHATOU (78) Le Patio Appartement neuf - 1 à 4 pièces
        #              Dès 245 000 € 2e trimestre 2028 PTZ TVA 5,5%"
        card_rx = re.compile(
            r"^\s*(.{2,60}?)\s+(Appartement neuf|Maison neuve|Terrain [àa] b[âa]tir)"
            r"\s*-\s*(.{0,40}?)\s+D[èe]s\s+([\d\s  ]{5,12})\s*€"
        )
        for city, dept, card in _split_city_cards(to_text(html)):
            if not _is_idf_dept(dept):
                continue
            m = card_rx.match(card)
            if not m or m.group(2) != "Appartement neuf":
                continue
            prog = Program(source=self.name, url=url, developer="Nexity")
            prog.name = m.group(1).strip()
            prog.city = _clean_city(city)
            prog.dept = dept
            prog.price_program_min = clean_number(m.group(4))
            prog.typologies = _typologies_from_text(m.group(3))
            prog.delivery_quarter, prog.delivery_year = parse_quarter(card)
            prog.fiscal = detect_fiscal(card)
            out.append(prog)
        return out


# ---------------------------------------------------------------------------
# trouver-un-logement-neuf
# ---------------------------------------------------------------------------

class TrouverUnLogementNeuf:
    name = "trouver-un-logement-neuf"
    base = "https://www.trouver-un-logement-neuf.com"

    def __init__(self, idf_city_slugs: set[str] | None = None) -> None:
        self.idf_city_slugs = idf_city_slugs or set()

    def discover(self, ctx: Context) -> list[str]:
        txt = ctx.fetcher.get(f"{self.base}/sitemap.txt")
        out = []
        for line in (txt or "").splitlines():
            line = line.strip()
            if not line.startswith("http") or "-programme-" not in line:
                continue
            m = re.search(r"/immobilier-neuf/(.+?)-programme-", line)
            if m and m.group(1) in self.idf_city_slugs:
                out.append(line)
        return sorted(set(out))

    def parse(self, ctx: Context, url: str, html: str) -> list[Program]:
        text = to_text(html)
        prog = Program(source=self.name, url=url)
        m = re.search(r"<h1[^>]*>(.*?)</h1>", html, re.S | re.I)
        prog.name = to_text(m.group(1)) if m else ""
        m = re.search(r"/immobilier-neuf/(.+?)-programme-", url)
        if m:
            prog.city = m.group(1).replace("-", " ").title()

        m = re.search(r"\b(\d{5})\b", text)
        if m:
            prog.postcode = m.group(1)
            prog.dept = prog.postcode[:2]
        m = re.search(r"(\d)\s*pi[èe]ces?\s+[àa] partir de\s+([\d\s  ]{5,12})\s*€", text)
        if m:
            prog.price_program_min = clean_number(m.group(2))
        m = re.search(r"Dispo\s*:\s*([\d,\s etpièces]{1,40})", text)
        if m:
            prog.typologies = _typologies_from_text(m.group(1))
        prog.delivery_quarter, prog.delivery_year = parse_quarter(text)
        prog.fiscal = detect_fiscal(text[:8000])
        return [prog] if prog.name else []


# ---------------------------------------------------------------------------
# coteneuf — publishes a lot table, but most prices are masked as "XXX".
# ---------------------------------------------------------------------------

class Coteneuf:
    name = "coteneuf"
    base = "https://www.coteneuf.com"

    def __init__(self, idf_city_slugs: set[str] | None = None) -> None:
        self.idf_city_slugs = idf_city_slugs or set()

    def discover(self, ctx: Context) -> list[str]:
        xml = ctx.fetcher.get(f"{self.base}/sitemap.xml")
        out = []
        for url in _sitemap_locs(xml):
            if "/programmes-immobiliers-neufs/" not in url:
                continue
            slug = url.rstrip("/").rsplit("/", 1)[-1]
            # The commune is the slug's suffix ("109-paris-epinay-sur-seine").
            # Substring matching would be wrong here: Val-d'Oise has a commune
            # called "Us", which appears inside "toulouse".
            if _suffix_in(slug, self.idf_city_slugs):
                out.append(url)
        return sorted(set(out))

    def parse(self, ctx: Context, url: str, html: str) -> list[Program]:
        text = to_text(html)
        prog = Program(source=self.name, url=url)
        m = re.search(r"<h1[^>]*>(.*?)</h1>", html, re.S | re.I)
        prog.name = to_text(m.group(1)) if m else ""
        m = re.search(r"\b(\d{5})\b", text)
        if m:
            prog.postcode = m.group(1)
            prog.dept = prog.postcode[:2]
        m = re.search(r"[ÀA]\s*partir de\s*([\d\s  ]{5,12})\s*€", text)
        if m:
            prog.price_program_min = clean_number(m.group(1))
        prog.delivery_quarter, prog.delivery_year = parse_quarter(text)
        prog.fiscal = detect_fiscal(text[:8000])
        prog.typologies = _typologies_from_text(text)

        # Lot rows: "Lot B502 Surface 70.7 m² Étage 5 ... À partir de 319 243 €"
        for m in re.finditer(
            r"Lot\s+\S+\s+Surface\s+([\d.,]+)\s*m²(.{0,120}?)([\d\s  ]{6,12})\s*€", text
        ):
            area = clean_number(m.group(1))
            price = clean_number(m.group(3))
            if not area or not price or price < 50000:
                continue
            # A 4-room flat is inferred from the surface bracket only when the
            # page states the typology in the same block.
            block = m.group(0)
            if re.search(r"\bT4\b|4 pi[èe]ces", block):
                prog.area_t4_min = min(filter(None, [prog.area_t4_min, area]))
                prog.price_t4_min = min(filter(None, [prog.price_t4_min, price]))
        return [prog] if prog.name else []


# ---------------------------------------------------------------------------

class Vinci:
    """VINCI Immobilier.

    Their sitemap index is broken (it literally points at ``undefined/...``),
    so discovery walks the published city index instead. Listing pages are
    server-rendered; robots.txt forbids every URL carrying a query string, so
    only clean paths are requested.
    """

    name = "vinci"
    base = "https://www.vinci-immobilier.com"
    idf_slugs = [
        "ile-de-france", "hauts-de-seine", "seine-et-marne", "seine-saint-denis",
        "val-de-marne", "val-d-oise", "yvelines",
        "appartements-neufs-et-immobilier-essonne",
    ]

    def discover(self, ctx: Context) -> list[str]:
        urls = {f"{self.base}/trouver-son-logement-neuf/{s}" for s in self.idf_slugs}
        index = ctx.fetcher.get(f"{self.base}/trouver-son-logement-neuf/toutes-les-villes")
        if index:
            for href in links(index, r"/trouver-son-logement-neuf/[a-z0-9\-]+$", self.base):
                m = re.search(r"-(\d{5})$", href)
                if m and _is_idf_dept(m.group(1)[:2]):
                    urls.add(href)
        return sorted(urls)

    def parse(self, ctx: Context, url: str, html: str) -> list[Program]:
        out: list[Program] = []
        for city, dept, card in _split_city_cards(to_text(html)):
            if not _is_idf_dept(dept):
                continue
            m = re.search(r"[ÀA]\s*partir\s*de\s*([\d\s  ]{5,12})\s*€", card)
            if not m:
                continue
            prog = Program(source=self.name, url=url, developer="VINCI Immobilier")
            # Everything before the badges/price is the programme name.
            head = card[: m.start()]
            head = re.split(
                r"\b(?:Avant-Premi[èe]re|En travaux|[ÀA] d[ée]couvrir|Commercialisation"
                r"|Livr(?:aison|[ée])|Derni[èe]re?s?|Nouveaut[ée]|Offres?"
                r"|TVA r[ée]duite|LMNP|LLI|Jeanbrun|PTZ|BRS)\b",
                head,
            )[0]
            prog.name = head.strip(" -•·|")
            prog.city = city.strip().title()
            prog.dept = dept
            prog.price_program_min = clean_number(m.group(1))
            prog.typologies = _typologies_from_text(card)
            prog.delivery_quarter, prog.delivery_year = parse_quarter(card)
            prog.fiscal = detect_fiscal(card)
            if prog.name:
                out.append(prog)
        return out


class Diagonale:
    """Diagonale — small IDF portfolio, program pages are client-rendered so
    only the JSON-LD envelope and the visible text carry usable facts."""

    name = "diagonale"
    base = "https://diagonale.fr"

    def discover(self, ctx: Context) -> list[str]:
        xml = ctx.fetcher.get(f"{self.base}/wp-sitemap-posts-prog-1.xml")
        return sorted(
            {
                u for u in _sitemap_locs(xml)
                if "/programmes-immobiliers-neufs/paris/" in u
                or "/ile-de-france/" in u
            }
        )

    def parse(self, ctx: Context, url: str, html: str) -> list[Program]:
        text = to_text(html)
        prog = Program(source=self.name, url=url, developer="Diagonale")
        m = re.search(r"<h1[^>]*>(.*?)</h1>", html, re.S | re.I)
        prog.name = to_text(m.group(1)) if m else ""
        m = re.search(r"/programmes-immobiliers-neufs/[^/]+/([^/]+)/", url)
        if m:
            prog.city = m.group(1).replace("-", " ").title()
        m = re.search(r"\b(\d{5})\b", text)
        if m:
            prog.postcode = m.group(1)
            prog.dept = prog.postcode[:2]
        m = re.search(r"[àa]\s*partir\s*de\s*([\d\s  ]{5,12})\s*€", text, re.I)
        if m:
            prog.price_program_min = clean_number(m.group(1))
        prog.delivery_quarter, prog.delivery_year = parse_quarter(text)
        prog.fiscal = detect_fiscal(text[:8000])
        prog.typologies = _typologies_from_text(text)
        prog.notes = "page client-rendered : données partielles"
        return [prog] if prog.name else []


# Includes Ÿ/Œ/Æ and friends, which fall outside the À-Ü range and would
# otherwise cut "L'HAŸ-LES-ROSES" in half.
_UPPER = "A-ZÀ-ÖØ-ÞŸŒÆ"
_CITY_BOUNDARY = re.compile(rf"([{_UPPER}][{_UPPER}'’\- ]{{2,40}}?)\s*\(\s*(\d{{2}})\s*\)")


def _suffix_in(slug: str, names: set[str]) -> bool:
    """True when some trailing run of ``slug``'s '-' parts is a known commune."""
    parts = slug.split("-")
    # Communes run up to ~6 tokens ("saint-germain-en-laye", "l-hay-les-roses").
    for start in range(max(0, len(parts) - 7), len(parts)):
        if "-".join(parts[start:]) in names:
            return True
    return False


_PLAN_ASSET = re.compile(
    r'(?:href|src)="(https?://[^"]*(?:plan|sitePlans)[^"]*\.pdf[^"]*)"', re.I
)


def _public_plan_link(html: str) -> str:
    """A plan asset the page links to openly, with no form in between.

    Only absolute links are taken, so the caller can check that host's own
    robots.txt before ever fetching the file.
    """
    m = _PLAN_ASSET.search(html or "")
    return m.group(1) if m else ""


_BADGE_PREFIX = re.compile(
    r"^(?:\s*(?:PTZ|LMNP|LLI|BRS|ANRU|TVA(?:\s*(?:r[ée]duite|5[,.]5\s*%?|7\s*%?))?"
    r"|Jeanbrun|Pinel|Maison\s*\+\s*Terrain|Nouveaut[ée])\b[\s,]*)+",
    re.I,
)


def _clean_city(raw: str) -> str:
    """Listing badges sit in the same uppercase run as the city name."""
    return _BADGE_PREFIX.sub("", raw or "").strip(" -•·|").title()


def _split_city_cards(text: str) -> list[tuple[str, str, str]]:
    """Slice a listing page into (city, dept, card-text) triples.

    Listing pages repeat a "CITY (DD) …" block per programme; cutting on that
    boundary keeps one card's price and delivery date from bleeding into the
    next one's.
    """
    marks = list(_CITY_BOUNDARY.finditer(text))
    out = []
    for i, m in enumerate(marks):
        end = marks[i + 1].start() if i + 1 < len(marks) else len(text)
        out.append((m.group(1), m.group(2), text[m.end():end]))
    return out


def _typologies_from_text(text: str) -> list[int]:
    """Room counts mentioned as 'T4', '4 pièces', 'du 2 au 5 pièces', '1 à 4'."""
    if not text:
        return []
    found: set[int] = set()
    low = text.lower()

    # Ranges first: "du studio au 5 pièces", "du T2 au T5", "1 à 4 pièces".
    range_rx = (
        r"\b(?:d[ue]\s*)?(studios?|t?[1-6])\s*(?:pi[èe]ces?\s*)?(?:au|[àa])\s*(?:t)?([1-6])\b",
        r"\b(studios?|[1-6])\s*[àa]\s*([1-6])\s*pi[èe]ces?\b",
    )
    for pattern in range_rx:
        for m in re.finditer(pattern, low):
            lo_raw = m.group(1)
            lo = 1 if lo_raw.startswith("studio") else int(lo_raw.lstrip("t"))
            hi = int(m.group(2))
            if lo <= hi:
                found.update(range(lo, hi + 1))

    # Comma-separated lists: "Dispo : 1, 2, 3, 4 pièces".
    for m in re.finditer(r"\b((?:[1-6]\s*,\s*){1,5}[1-6])\s*(?:et\s*[1-6]\s*)?pi[èe]ces?\b", low):
        found.update(int(x) for x in re.findall(r"[1-6]", m.group(1)))

    for m in re.finditer(r"\bt([1-6])\b", low):
        found.add(int(m.group(1)))
    for m in re.finditer(r"\b([1-6])\s*pi[èe]ces?\b", low):
        found.add(int(m.group(1)))
    if re.search(r"\bstudio\b", low):
        found.add(1)
    return sorted(found)


ALL_SOURCES = [
    Explorimmoneuf,
    Bouygues,
    KaufmanBroad,
    Sogeprom,
    Nexity,
    Vinci,
    Diagonale,
    TrouverUnLogementNeuf,
    Coteneuf,
]
