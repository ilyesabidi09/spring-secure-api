"""Polite, cached HTTP client.

Three properties matter here: we never fetch a URL robots.txt forbids, we never
issue more than one request per host per ``min_interval`` seconds, and every
response is cached on disk so re-running the pipeline costs the sites nothing.
"""

from __future__ import annotations

import gzip
import hashlib
import io
import random
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
import zlib
from pathlib import Path

from .robots import RobotsGuard

BROWSER_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "fr-FR,fr;q=0.9,en;q=0.8",
    "Accept-Encoding": "gzip, deflate",
    "Upgrade-Insecure-Requests": "1",
    "Connection": "close",
}


class RobotsDenied(Exception):
    """Raised when robots.txt forbids the URL."""


class Fetcher:
    def __init__(
        self,
        cache_dir: Path,
        guard: RobotsGuard | None = None,
        min_interval: float = 1.5,
        timeout: int = 45,
        max_retries: int = 3,
    ) -> None:
        self.cache_dir = Path(cache_dir)
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        self.guard = guard or RobotsGuard()
        self.min_interval = min_interval
        self.timeout = timeout
        self.max_retries = max_retries
        self._last_hit: dict[str, float] = {}
        self._lock = threading.Lock()
        self.stats = {"cache": 0, "network": 0, "robots_denied": 0, "errors": 0}

    def _cache_path(self, url: str) -> Path:
        digest = hashlib.sha256(url.encode("utf-8")).hexdigest()[:24]
        return self.cache_dir / f"{digest}.html"

    def _throttle(self, host: str) -> None:
        while True:
            with self._lock:
                now = time.monotonic()
                last = self._last_hit.get(host, 0.0)
                wait = self.min_interval - (now - last)
                if wait <= 0:
                    self._last_hit[host] = now
                    return
            time.sleep(wait + random.uniform(0.05, 0.35))

    @staticmethod
    def _decode(resp, raw: bytes) -> str:
        encoding = (resp.headers.get("Content-Encoding") or "").lower()
        if "gzip" in encoding:
            try:
                raw = gzip.GzipFile(fileobj=io.BytesIO(raw)).read()
            except OSError:
                pass
        elif "deflate" in encoding:
            try:
                raw = zlib.decompress(raw, -zlib.MAX_WBITS)
            except zlib.error:
                pass
        charset = resp.headers.get_content_charset() or "utf-8"
        return raw.decode(charset, errors="replace")

    def get(self, url: str, use_cache: bool = True) -> str | None:
        """Return the body, or None if the fetch failed.

        Raises :class:`RobotsDenied` when robots.txt forbids the URL, so that
        callers can count exclusions rather than silently skipping them.
        """
        path = self._cache_path(url)
        if use_cache and path.exists():
            self.stats["cache"] += 1
            return path.read_text(encoding="utf-8", errors="replace")

        if not self.guard.allowed(url):
            self.stats["robots_denied"] += 1
            raise RobotsDenied(url)

        host = urllib.parse.urlsplit(url).netloc
        body: str | None = None
        for attempt in range(self.max_retries):
            self._throttle(host)
            try:
                req = urllib.request.Request(url, headers=BROWSER_HEADERS)
                with urllib.request.urlopen(req, timeout=self.timeout) as resp:
                    body = self._decode(resp, resp.read())
                break
            except urllib.error.HTTPError as exc:
                if exc.code in (404, 410, 403):
                    self.stats["errors"] += 1
                    return None
                time.sleep(2 ** attempt)
            except Exception:
                time.sleep(2 ** attempt)

        if body is None:
            self.stats["errors"] += 1
            return None

        self.stats["network"] += 1
        path.write_text(body, encoding="utf-8")
        return body
