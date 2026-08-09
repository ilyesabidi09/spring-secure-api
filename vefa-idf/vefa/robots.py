"""robots.txt fetching and enforcement.

Implements the Google/REP matching rules (``*`` wildcard, ``$`` end-anchor,
longest-match-wins between Allow and Disallow), which ``urllib.robotparser``
does not handle reliably. Every outbound request in this project goes through
:meth:`RobotsGuard.allowed` first; a URL that is disallowed is never fetched.
"""

from __future__ import annotations

import re
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass, field

USER_AGENT = "vefa-idf-research/1.0 (personal apartment search; contact via site owner)"


def _rule_to_regex(path: str) -> re.Pattern[str]:
    """Translate a robots.txt path pattern into a regex.

    ``*`` matches any sequence, a trailing ``$`` anchors the end of the URL,
    everything else is literal.
    """
    anchored = path.endswith("$")
    if anchored:
        path = path[:-1]
    out = []
    for ch in path:
        if ch == "*":
            out.append(".*")
        else:
            out.append(re.escape(ch))
    return re.compile("^" + "".join(out) + ("$" if anchored else ""))


@dataclass
class _Group:
    allows: list[tuple[int, re.Pattern[str]]] = field(default_factory=list)
    disallows: list[tuple[int, re.Pattern[str]]] = field(default_factory=list)


class RobotsGuard:
    """Caches and evaluates robots.txt for every host touched."""

    def __init__(self, user_agent: str = USER_AGENT, timeout: int = 30) -> None:
        self.user_agent = user_agent
        self.timeout = timeout
        self._cache: dict[str, _Group | None] = {}
        self._lock = threading.Lock()
        self.sitemaps: dict[str, list[str]] = {}

    # Some hosts sit behind a WAF that answers 403 to unknown clients, which
    # would leave us with no policy at all. We ask with ordinary browser
    # headers so we actually receive the file, then obey the "*" group in it.
    _HEADERS = {
        "User-Agent": (
            "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
            "(KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36"
        ),
        "Accept": "text/plain,text/html;q=0.9,*/*;q=0.8",
        "Accept-Language": "fr-FR,fr;q=0.9",
    }

    def _fetch(self, origin: str) -> str:
        last_error: Exception | None = None
        for _ in range(3):
            try:
                req = urllib.request.Request(
                    origin + "/robots.txt", headers=self._HEADERS
                )
                with urllib.request.urlopen(req, timeout=self.timeout) as resp:
                    return resp.read().decode("utf-8", errors="replace")
            except urllib.error.HTTPError as exc:
                if exc.code == 404:
                    return ""  # no policy published: crawling is unrestricted
                last_error = exc
            except Exception as exc:  # network hiccup
                last_error = exc
            time.sleep(1.5)
        raise last_error or RuntimeError("robots.txt unreachable")

    def _parse(self, text: str, origin: str) -> _Group:
        """Select the group whose User-agent best matches ours.

        A group headed by our exact token wins; otherwise the ``*`` group is
        used. Consecutive ``User-agent`` lines share one group of rules.
        """
        groups: dict[str, _Group] = {}
        current: list[str] = []
        expecting_agents = True
        sitemaps: list[str] = []

        for raw_line in text.splitlines():
            line = raw_line.split("#", 1)[0].strip()
            if not line or ":" not in line:
                continue
            field_name, _, value = line.partition(":")
            field_name = field_name.strip().lower()
            value = value.strip()

            if field_name == "sitemap":
                sitemaps.append(value)
                continue
            if field_name == "user-agent":
                if not expecting_agents:
                    current = []
                    expecting_agents = True
                current.append(value.lower())
                groups.setdefault(value.lower(), _Group())
                continue
            if field_name not in ("allow", "disallow"):
                continue

            expecting_agents = False
            if not value and field_name == "disallow":
                # "Disallow:" with an empty value means "allow everything".
                continue
            pattern = _rule_to_regex(value)
            for agent in current:
                group = groups.setdefault(agent, _Group())
                target = group.allows if field_name == "allow" else group.disallows
                target.append((len(value), pattern))

        self.sitemaps[origin] = sitemaps
        token = self.user_agent.split("/", 1)[0].lower()
        for key in (token, "*"):
            if key in groups:
                return groups[key]
        return _Group()

    def _group_for(self, origin: str) -> _Group | None:
        with self._lock:
            if origin in self._cache:
                return self._cache[origin]
        try:
            group = self._parse(self._fetch(origin), origin)
        except Exception:
            # Policy could not be read. Fail closed: we do not crawl a host
            # whose rules we were unable to obtain.
            group = None
        with self._lock:
            self._cache[origin] = group
        return group

    def allowed(self, url: str) -> bool:
        parts = urllib.parse.urlsplit(url)
        origin = f"{parts.scheme}://{parts.netloc}"
        group = self._group_for(origin)
        if group is None:
            return False
        path = parts.path or "/"
        if parts.query:
            path += "?" + parts.query

        best_allow = max(
            (length for length, pattern in group.allows if pattern.match(path)),
            default=-1,
        )
        best_disallow = max(
            (length for length, pattern in group.disallows if pattern.match(path)),
            default=-1,
        )
        if best_disallow < 0:
            return True
        # Ties go to Allow, per the REP specification.
        return best_allow >= best_disallow

    def sitemaps_for(self, origin: str) -> list[str]:
        self._group_for(origin)
        return self.sitemaps.get(origin, [])
