"""The annotation page: its data, its decisions, and the server's guards.

The ledger is the invented AIB fixture; every payee and amount is invented.
"""

from __future__ import annotations

import json
import logging
import sqlite3
import threading
import urllib.error
import urllib.request
from collections.abc import Iterator
from pathlib import Path

import pytest

from annotate import (
    confirm_proposals,
    decide_payee,
    label_transactions,
    page_state,
    payee_transactions,
)
from ingest import import_statement
from models import Account
from parsers import aib_csv
from store import add_account, add_category_rule, open_db
from tests.test_cli import FIXTURE
from ui_server import STATIC_DIR, make_handler


@pytest.fixture
def ledger(tmp_path: Path) -> Path:
    """A ledger file holding the invented AIB fixture."""
    db = tmp_path / "ledger.db"
    conn = open_db(db)
    with conn:
        account = add_account(
            conn,
            Account(
                name="aib-current", institution="AIB", kind="current", currency="EUR"
            ),
        )
    content = FIXTURE.read_bytes()
    import_statement(
        conn,
        account=account,
        statement=aib_csv.parse(content),
        content=content,
        source_name="export.csv",
        archive_root=tmp_path / "sources",
    )
    conn.close()
    return db


@pytest.fixture
def conn(ledger: Path) -> Iterator[sqlite3.Connection]:
    connection = open_db(ledger)
    yield connection
    connection.close()


class TestPageState:
    def test_shape_and_coverage(self, conn: sqlite3.Connection) -> None:
        state = page_state(conn)
        assert state["currency"] == "EUR"
        keys = {p["key"] for p in state["payees"]}
        assert {"CORNERCAFE", "EXAMPLEMORTGA"} <= keys
        coverage = state["coverage"]
        # Only the cash withdrawal and the fee are named, by their channel.
        assert coverage["classified_permille"] < 200
        assert [y["label"] for y in state["years"]] == ["2026", "All"]
        assert state["years"][0]["partial"] is True

    def test_unclassified_money_in_is_not_a_refund(
        self, conn: sqlite3.Connection
    ) -> None:
        period = page_state(conn)["years"][-1]
        # Salary arrives unclassified; it must not cancel out spending.
        assert period["spend"]["minor"] > 0
        assert period["unclassified_out"]["minor"] > 0

    def test_proposal_shows_until_decided(self, conn: sqlite3.Connection) -> None:
        with conn:
            add_category_rule(
                conn,
                counterparty_key="CORNERCAFE",
                category="eating-out",
                source="claude",
                status="proposed",
                confidence="high",
            )
        cafe = next(p for p in page_state(conn)["payees"] if p["key"] == "CORNERCAFE")
        assert cafe["proposal"]["category"] == "eating-out"
        assert cafe["category"] == "unclassified"

        assert confirm_proposals(conn, keys=["CORNERCAFE"]) == 1
        cafe = next(p for p in page_state(conn)["payees"] if p["key"] == "CORNERCAFE")
        assert cafe["proposal"] is None
        assert cafe["decided"] == "eating-out"
        assert cafe["category"] == "eating-out"


class TestDecisions:
    def test_decide_and_none(self, conn: sqlite3.Connection) -> None:
        decide_payee(conn, "EXAMPLEMORTGA", "housing")
        rows = payee_transactions(conn, "EXAMPLEMORTGA")
        assert {r["category"] for r in rows} == {"housing"}
        decide_payee(conn, "EXAMPLEMORTGA", "none")
        assert {r["category"] for r in payee_transactions(conn, "EXAMPLEMORTGA")} == {
            "unclassified"
        }

    def test_unknown_payee(self, conn: sqlite3.Connection) -> None:
        with pytest.raises(ValueError, match="NOSUCH"):
            decide_payee(conn, "NOSUCH", "housing")

    def test_label_wins_and_keeps_its_note(self, conn: sqlite3.Connection) -> None:
        decide_payee(conn, "CORNERCAFE", "eating-out")
        first = payee_transactions(conn, "CORNERCAFE")[0]
        label_transactions(conn, [first["id"]], "gifts-charity", "A treat for a friend")
        rows = {r["id"]: r for r in payee_transactions(conn, "CORNERCAFE")}
        assert rows[first["id"]]["category"] == "gifts-charity"
        assert rows[first["id"]]["basis"] == "label"
        assert rows[first["id"]]["note"] == "A treat for a friend"
        others = [r for r in rows.values() if r["id"] != first["id"]]
        assert {r["category"] for r in others} == {"eating-out"}

    def test_label_of_unknown_transaction_writes_nothing(
        self, conn: sqlite3.Connection
    ) -> None:
        first = payee_transactions(conn, "CORNERCAFE")[0]
        with pytest.raises(ValueError):
            label_transactions(conn, [first["id"], 99999], "groceries")
        count = conn.execute("SELECT COUNT(*) FROM transaction_labels").fetchone()[0]
        assert count == 0


class _Server:
    def __init__(self, db: Path) -> None:
        from http.server import ThreadingHTTPServer

        self.token = "test-token-0123456789"
        self.httpd = ThreadingHTTPServer(("127.0.0.1", 0), make_handler(db, self.token))
        self.port = self.httpd.server_address[1]
        self.thread = threading.Thread(target=self.httpd.serve_forever, daemon=True)
        self.thread.start()

    def request(
        self,
        path: str,
        *,
        body: object | None = None,
        token: str | None = "",
        headers: dict[str, str] | None = None,
    ) -> tuple[int, bytes]:
        sent = {"X-Finch-Token": self.token if token == "" else (token or "")}
        sent.update(headers or {})
        data = json.dumps(body).encode() if body is not None else None
        req = urllib.request.Request(
            f"http://127.0.0.1:{self.port}{path}", data=data, headers=sent
        )
        try:
            with urllib.request.urlopen(req) as res:
                return res.status, res.read()
        except urllib.error.HTTPError as err:
            return err.code, err.read()


@pytest.fixture
def server(ledger: Path) -> Iterator[_Server]:
    running = _Server(ledger)
    yield running
    running.httpd.shutdown()
    running.httpd.server_close()


class TestServer:
    def test_page_needs_the_token_and_embeds_it(self, server: _Server) -> None:
        status, _ = server.request("/")
        assert status == 403
        status, body = server.request(f"/?t={server.token}")
        assert status == 200
        assert server.token.encode() in body
        assert b"__FINCH_TOKEN__" not in body

    def test_static_files(self, server: _Server) -> None:
        for name in ("app.js", "style.css"):
            status, body = server.request(f"/{name}")
            assert status == 200
            assert body == (STATIC_DIR / name).read_bytes()

    def test_api_needs_the_token(self, server: _Server) -> None:
        assert server.request("/api/state", token=None)[0] == 403
        assert server.request("/api/state", token="wrong")[0] == 403
        status, body = server.request("/api/state")
        assert status == 200
        assert json.loads(body)["currency"] == "EUR"

    def test_foreign_host_is_refused(self, server: _Server) -> None:
        status, _ = server.request(
            "/api/state", headers={"Host": f"rebound.example:{server.port}"}
        )
        assert status == 403

    def test_foreign_origin_cannot_write(self, server: _Server) -> None:
        status, _ = server.request(
            "/api/decide",
            body={"key": "CORNERCAFE", "category": "eating-out"},
            headers={
                "Origin": "http://elsewhere.example",
                "Content-Type": "application/json",
            },
        )
        assert status == 403

    def test_decide_label_and_errors(self, server: _Server) -> None:
        status, _ = server.request(
            "/api/decide",
            body={"key": "CORNERCAFE", "category": "eating-out"},
            headers={"Content-Type": "application/json"},
        )
        assert status == 200
        status, body = server.request("/api/payee?key=CORNERCAFE")
        rows = json.loads(body)["transactions"]
        assert {r["category"] for r in rows} == {"eating-out"}

        status, _ = server.request(
            "/api/label",
            body={"ids": [rows[0]["id"]], "category": "gifts-charity", "note": "Gift"},
            headers={"Content-Type": "application/json"},
        )
        assert status == 200

        status, body = server.request(
            "/api/decide",
            body={"key": "CORNERCAFE", "category": "rent"},
            headers={"Content-Type": "application/json"},
        )
        assert status == 400
        assert "Unknown category" in json.loads(body)["error"]

        status, _ = server.request(
            "/api/decide",
            body={"category": "housing"},
            headers={"Content-Type": "application/json"},
        )
        assert status == 400

    def test_log_never_carries_payee_names(
        self, server: _Server, caplog: pytest.LogCaptureFixture
    ) -> None:
        with caplog.at_level(logging.DEBUG, logger="ui_server"):
            server.request("/api/payee?key=CORNERCAFE")
        assert caplog.records
        assert all("CORNERCAFE" not in record.getMessage() for record in caplog.records)
