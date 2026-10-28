"""Local web server for the annotation page: ``main.py ui``.

It listens on loopback only and serves the static page in ``src/ui/`` plus a
small JSON API over ``annotate``. Every API call must carry the session's
random token, which only the page served at the address printed on start
knows, and every request must name this server in its Host header. Together
they stop another website in the same browser from reading or writing the
ledger through the loopback port, including by DNS rebinding.

Request logging records the method and path only, never a query string or
body, since those carry payee names.

Public API:
    serve -- run the page until interrupted

Example:
    from ui_server import serve

    serve(profile.db, port=0, open_browser=True)
"""

from __future__ import annotations

import json
import logging
import secrets
import sqlite3
import webbrowser
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlsplit

from annotate import (
    confirm_proposals,
    decide_payee,
    label_transactions,
    page_state,
    payee_transactions,
)
from config import UI_HOST
from store import open_existing_db

logger = logging.getLogger(__name__)

STATIC_DIR = Path(__file__).parent / "ui"
_STATIC: dict[str, str] = {
    "/app.js": "text/javascript; charset=utf-8",
    "/style.css": "text/css; charset=utf-8",
}
_TOKEN_PLACEHOLDER = "__FINCH_TOKEN__"
_MAX_BODY = 64 * 1024


def make_handler(db: Path, token: str) -> type[BaseHTTPRequestHandler]:
    """Build a request handler bound to one ledger and one session token."""

    class Handler(BaseHTTPRequestHandler):
        server_version = "finch"

        def log_message(self, format: str, *args: object) -> None:  # noqa: A002
            logger.debug("%s %s", self.command, urlsplit(self.path).path)

        # -- guards -------------------------------------------------------

        def _host_ok(self) -> bool:
            port = self.server.server_address[1]
            return self.headers.get("Host") in (
                f"127.0.0.1:{port}",
                f"localhost:{port}",
            )

        def _token_ok(self) -> bool:
            sent = self.headers.get("X-Finch-Token", "")
            return secrets.compare_digest(sent, token)

        # -- responses ----------------------------------------------------

        def _send(self, status: int, body: bytes, content_type: str) -> None:
            self.send_response(status)
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            self.send_header("X-Content-Type-Options", "nosniff")
            self.send_header("Referrer-Policy", "no-referrer")
            self.send_header(
                "Content-Security-Policy",
                "default-src 'self'; style-src 'self'; script-src 'self'; "
                "img-src 'self' data:; connect-src 'self'; frame-ancestors 'none'",
            )
            self.end_headers()
            self.wfile.write(body)

        def _json(self, status: int, payload: object) -> None:
            self._send(status, json.dumps(payload).encode(), "application/json")

        def _with_db(self, work):  # noqa: ANN001, ANN202
            conn: sqlite3.Connection = open_existing_db(db)
            try:
                return work(conn)
            finally:
                conn.close()

        # -- routes -------------------------------------------------------

        def do_GET(self) -> None:  # noqa: N802
            if not self._host_ok():
                self._send(HTTPStatus.FORBIDDEN, b"Forbidden", "text/plain")
                return
            url = urlsplit(self.path)
            if url.path == "/":
                query = parse_qs(url.query)
                if not secrets.compare_digest(query.get("t", [""])[0], token):
                    self._send(
                        HTTPStatus.FORBIDDEN,
                        b"Open the address 'main.py ui' printed; it carries this "
                        b"session's token.",
                        "text/plain; charset=utf-8",
                    )
                    return
                page = (STATIC_DIR / "index.html").read_text(encoding="utf-8")
                self._send(
                    HTTPStatus.OK,
                    page.replace(_TOKEN_PLACEHOLDER, token).encode(),
                    "text/html; charset=utf-8",
                )
                return
            if url.path in _STATIC:
                body = (STATIC_DIR / url.path.lstrip("/")).read_bytes()
                self._send(HTTPStatus.OK, body, _STATIC[url.path])
                return
            if not url.path.startswith("/api/"):
                self._send(HTTPStatus.NOT_FOUND, b"Not found", "text/plain")
                return
            if not self._token_ok():
                self._json(HTTPStatus.FORBIDDEN, {"error": "Missing or wrong token."})
                return
            try:
                if url.path == "/api/state":
                    self._json(HTTPStatus.OK, self._with_db(page_state))
                elif url.path == "/api/payee":
                    key = parse_qs(url.query).get("key", [""])[0]
                    rows = self._with_db(lambda c: payee_transactions(c, key))
                    self._json(HTTPStatus.OK, {"transactions": rows})
                else:
                    self._json(HTTPStatus.NOT_FOUND, {"error": "No such endpoint."})
            except ValueError as exc:
                self._json(HTTPStatus.BAD_REQUEST, {"error": str(exc)})

        def do_POST(self) -> None:  # noqa: N802
            port = self.server.server_address[1]
            origin = self.headers.get("Origin")
            if (
                not self._host_ok()
                or not self._token_ok()
                or (
                    origin
                    and origin
                    not in (f"http://127.0.0.1:{port}", f"http://localhost:{port}")
                )
            ):
                self._json(HTTPStatus.FORBIDDEN, {"error": "Forbidden."})
                return
            length = int(self.headers.get("Content-Length") or 0)
            if length > _MAX_BODY:
                self._json(HTTPStatus.REQUEST_ENTITY_TOO_LARGE, {"error": "Too large."})
                return
            try:
                body = json.loads(self.rfile.read(length) or b"{}")
                path = urlsplit(self.path).path
                if path == "/api/decide":
                    self._with_db(
                        lambda c: decide_payee(
                            c, body["key"], body["category"], body.get("note")
                        )
                    )
                    self._json(HTTPStatus.OK, {"ok": True})
                elif path == "/api/confirm":
                    count = self._with_db(
                        lambda c: confirm_proposals(c, keys=list(body["keys"]))
                    )
                    self._json(HTTPStatus.OK, {"confirmed": count})
                elif path == "/api/label":
                    ids = [int(i) for i in body["ids"]]
                    self._with_db(
                        lambda c: label_transactions(
                            c, ids, body["category"], body.get("note")
                        )
                    )
                    self._json(HTTPStatus.OK, {"ok": True})
                else:
                    self._json(HTTPStatus.NOT_FOUND, {"error": "No such endpoint."})
            except (KeyError, TypeError, json.JSONDecodeError):
                self._json(HTTPStatus.BAD_REQUEST, {"error": "Malformed request."})
            except ValueError as exc:
                self._json(HTTPStatus.BAD_REQUEST, {"error": str(exc)})

    return Handler


def serve(db: Path, *, port: int = 0, open_browser: bool = True) -> None:
    """Serve the annotation page until Ctrl-C.

    Args:
        db: The profile's ledger database.
        port: Port on loopback; 0 picks a free one.
        open_browser: Open the page in the default browser.
    """
    token = secrets.token_urlsafe(24)
    server = ThreadingHTTPServer((UI_HOST, port), make_handler(db, token))
    url = f"http://127.0.0.1:{server.server_address[1]}/?t={token}"
    print(f"finch annotation page: {url}", flush=True)
    print("Press Ctrl-C to stop.", flush=True)
    if open_browser:
        webbrowser.open(url)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
