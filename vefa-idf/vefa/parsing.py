"""Low-level extraction helpers shared by every source."""

from __future__ import annotations

import html as html_mod
import json
import re

_SCRIPT_STYLE = re.compile(r"<(script|style)\b.*?</\1>", re.S | re.I)
_TAG = re.compile(r"<[^>]+>")


def to_text(html: str) -> str:
    """Strip markup down to a single normalised line of text."""
    body = _SCRIPT_STYLE.sub(" ", html)
    body = _TAG.sub(" ", body)
    body = html_mod.unescape(body)
    return re.sub(r"[\s  ]+", " ", body).strip()


def json_ld(html: str) -> list[dict]:
    """Every JSON-LD object on the page, @graph entries flattened in."""
    out: list[dict] = []
    for block in re.findall(
        r'<script[^>]*type=["\']application/ld\+json["\'][^>]*>(.*?)</script>',
        html,
        re.S | re.I,
    ):
        try:
            data = json.loads(block.strip())
        except Exception:
            continue
        items = data if isinstance(data, list) else [data]
        for item in items:
            if not isinstance(item, dict):
                continue
            if "@graph" in item and isinstance(item["@graph"], list):
                out.extend(x for x in item["@graph"] if isinstance(x, dict))
            else:
                out.append(item)
    return out


def json_ld_of_type(html: str, *types: str) -> dict | None:
    wanted = {t.lower() for t in types}
    for item in json_ld(html):
        itype = item.get("@type")
        names = {itype.lower()} if isinstance(itype, str) else {
            str(x).lower() for x in (itype or [])
        }
        if names & wanted:
            return item
    return None


class NuxtPayload:
    """Resolver for Nuxt's ``__NUXT_DATA__`` flat/indexed (devalue) payload.

    The payload is an array where every object's values are *indices* into that
    same array. ``resolve`` walks it back into ordinary Python structures.
    """

    _WRAPPERS = {"Reactive", "ShallowReactive", "Ref", "ShallowRef", "EmptyRef"}

    def __init__(self, nodes: list) -> None:
        self.nodes = nodes

    @classmethod
    def from_html(cls, html: str) -> "NuxtPayload | None":
        m = re.search(
            r'id="__NUXT_DATA__"[^>]*>(.*?)</script>', html, re.S
        )
        if not m:
            return None
        try:
            return cls(json.loads(m.group(1)))
        except Exception:
            return None

    def resolve(self, index, depth: int = 0):
        if depth > 18:
            return None
        if not isinstance(index, int) or not (0 <= index < len(self.nodes)):
            return index
        node = self.nodes[index]
        if isinstance(node, list):
            if node and node[0] in self._WRAPPERS:
                return self.resolve(node[1], depth + 1)
            return [self.resolve(x, depth + 1) for x in node]
        if isinstance(node, dict):
            return {k: self.resolve(v, depth + 1) for k, v in node.items()}
        return node

    def objects_with(self, *keys: str) -> list[dict]:
        """Every resolved object that declares all of ``keys``."""
        wanted = set(keys)
        out = []
        for i, node in enumerate(self.nodes):
            if isinstance(node, dict) and wanted <= set(node.keys()):
                resolved = self.resolve(i)
                if isinstance(resolved, dict):
                    out.append(resolved)
        return out


def absolute(base: str, href: str) -> str:
    from urllib.parse import urljoin

    return urljoin(base, href)


def links(html: str, pattern: str, base: str) -> list[str]:
    """All hrefs matching ``pattern``, absolutised and de-duplicated."""
    rx = re.compile(pattern)
    found = {
        absolute(base, h)
        for h in re.findall(r'href="([^"]+)"', html)
        if rx.search(h)
    }
    return sorted(found)
