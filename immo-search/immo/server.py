"""Zero-dependency HTTP server exposing the search API and the web UI.

Standard library only, on purpose: the tool has to run from a clean checkout
with nothing to install, and a search box is not worth a dependency tree.
"""

from __future__ import annotations

import json
import mimetypes
import re
import traceback
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlsplit

from .criteria import Criteria, CriteriaError
from .engine import Index

WEB_ROOT = Path(__file__).resolve().parent / "web"
MAX_BODY = 1 << 20  # 1 MiB is far more than any query needs


class Api:
    """Routing and handlers, kept free of HTTP plumbing so they stay testable."""

    def __init__(self, index: Index, meta: dict | None = None) -> None:
        self.index = index
        self.meta = meta or {}

    def handle(self, path: str, params: dict) -> tuple[int, dict]:
        if path == "/api/meta":
            return 200, self.meta_payload()
        if path == "/api/search":
            return 200, self.index.search(Criteria.from_params(params))
        if path == "/api/facets":
            return 200, {"facets": self.index.facets(Criteria.from_params(params))}
        m = re.match(r"^/api/listing/([A-Za-z0-9]+)$", path)
        if m:
            listing = self.index.by_id.get(m.group(1))
            if not listing:
                return 404, {"error": "listing inconnu"}
            return 200, {"listing": listing.as_dict()}
        m = re.match(r"^/api/comparables/([A-Za-z0-9]+)$", path)
        if m:
            listing = self.index.by_id.get(m.group(1))
            if not listing:
                return 404, {"error": "listing inconnu"}
            radius = float((params.get("radius") or ["1500"])[0])
            return 200, {"comparables": self.index.comparables(listing, radius_m=radius)}
        return 404, {"error": "route inconnue"}

    def meta_payload(self) -> dict:
        listings = self.index.listings
        return {
            **self.meta,
            "count": len(listings),
            "by_kind": {
                kind: sum(1 for l in listings if l.kind == kind)
                for kind in sorted({l.kind for l in listings})
            },
            "facets": self.index.facets(Criteria()),
        }


def make_handler(api: Api):
    class Handler(BaseHTTPRequestHandler):
        server_version = "immo-search"
        protocol_version = "HTTP/1.1"

        def log_message(self, fmt, *args):  # quieter console
            pass

        # ------------------------------------------------------------- helpers
        def _send(self, status: int, body: bytes, content_type: str) -> None:
            self.send_response(status)
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            self.send_header("X-Content-Type-Options", "nosniff")
            self.end_headers()
            if self.command != "HEAD":
                self.wfile.write(body)

        def _json(self, status: int, payload: dict) -> None:
            body = json.dumps(payload, ensure_ascii=False, default=str).encode("utf-8")
            self._send(status, body, "application/json; charset=utf-8")

        def _static(self, path: str) -> None:
            name = "index.html" if path in ("/", "") else path.lstrip("/")
            target = (WEB_ROOT / name).resolve()
            # Never serve outside the web root, whatever the URL says.
            if not str(target).startswith(str(WEB_ROOT.resolve())) or not target.is_file():
                self._json(404, {"error": "not found"})
                return
            ctype, _ = mimetypes.guess_type(str(target))
            self._send(200, target.read_bytes(), ctype or "application/octet-stream")

        # -------------------------------------------------------------- routes
        def do_GET(self):
            parts = urlsplit(self.path)
            if not parts.path.startswith("/api/"):
                self._static(parts.path)
                return
            params = parse_qs(parts.query, keep_blank_values=False)
            try:
                status, payload = api.handle(parts.path, params)
            except CriteriaError as exc:
                self._json(400, {"error": str(exc)})
                return
            except Exception:
                traceback.print_exc()
                self._json(500, {"error": "erreur interne"})
                return
            self._json(status, payload)

        do_HEAD = do_GET

        def do_POST(self):
            parts = urlsplit(self.path)
            length = int(self.headers.get("Content-Length") or 0)
            if length > MAX_BODY:
                self._json(413, {"error": "requête trop volumineuse"})
                return
            raw = self.rfile.read(length) if length else b"{}"
            try:
                params = json.loads(raw.decode("utf-8") or "{}")
            except ValueError:
                self._json(400, {"error": "JSON invalide"})
                return
            try:
                status, payload = api.handle(parts.path, params)
            except CriteriaError as exc:
                self._json(400, {"error": str(exc)})
                return
            except Exception:
                traceback.print_exc()
                self._json(500, {"error": "erreur interne"})
                return
            self._json(status, payload)

    return Handler


def serve(index: Index, meta: dict, host: str = "127.0.0.1", port: int = 8000) -> None:
    api = Api(index, meta)
    httpd = ThreadingHTTPServer((host, port), make_handler(api))
    print(f"immo-search → http://{host}:{port}  ({len(index)} biens indexés)")
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        httpd.server_close()
