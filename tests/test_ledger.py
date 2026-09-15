"""Running-balance walks and derived balances."""

from __future__ import annotations

import sqlite3
from datetime import date
from pathlib import Path

from ingest import import_statement
from ledger import balance_breaks, latest_balance, running_balance_breaks
from models import Account
from tests.factories import row, statement


class TestRunningBalanceBreaks:
    def test_nothing_to_check_without_balances(self) -> None:
        assert running_balance_breaks([(-100, None), (-200, None)]) == ([], None)

    def test_opening_anchors_the_first_row(self) -> None:
        breaks, final = running_balance_breaks([(-100, 800)], opening=1000)
        assert breaks == [(0, 900, 800)]
        assert final == 800

    def test_reanchors_so_one_gap_is_reported_once(self) -> None:
        breaks, _ = running_balance_breaks([(-100, 900), (-100, 700), (-100, 600)])
        assert breaks == [(1, 800, 700)]


class TestLedger:
    def test_continuous_statements_have_no_breaks(
        self, conn: sqlite3.Connection, account: Account, tmp_path: Path
    ) -> None:
        for content, rows in (
            (b"aug", [row("2026-08-31", -1000, balance=9000)]),
            (b"sep", [row("2026-09-01", -500, balance=8500)]),
        ):
            import_statement(
                conn,
                account=account,
                statement=statement(*rows),
                content=content,
                source_name="s.csv",
                archive_root=tmp_path,
            )
        assert balance_breaks(conn, account.id) == []

    def test_latest_balance_carries_rows_after_the_last_printed_one(
        self, conn: sqlite3.Connection, account: Account, tmp_path: Path
    ) -> None:
        import_statement(
            conn,
            account=account,
            statement=statement(
                row("2026-09-01", -1000, balance=9000), row("2026-09-02", -500)
            ),
            content=b"x",
            source_name="s.csv",
            archive_root=tmp_path,
        )
        assert latest_balance(conn, account.id) == (date(2026, 9, 2), 8500)

    def test_latest_balance_unknown_without_any_printed_balance(
        self, conn: sqlite3.Connection, account: Account
    ) -> None:
        assert latest_balance(conn, account.id) is None
