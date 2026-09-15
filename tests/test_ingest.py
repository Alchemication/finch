"""Statement checks, row identity, and the import pipeline."""

from __future__ import annotations

import sqlite3
import stat
from datetime import date
from pathlib import Path

import pytest

from config import REPOSITORY_ROOT
from ingest import (
    ImportRejected,
    ImportResult,
    check_statement,
    identity_keys,
    import_statement,
)
from ledger import BalanceBreak
from models import Account, ParsedStatement
from sources import archive_source
from tests.factories import row, statement


def _import(
    conn: sqlite3.Connection,
    account: Account,
    parsed: ParsedStatement,
    tmp_path: Path,
    *,
    content: bytes = b"file-a",
    name: str = "export.csv",
) -> ImportResult:
    return import_statement(
        conn,
        account=account,
        statement=parsed,
        content=content,
        source_name=name,
        archive_root=tmp_path / "sources",
    )


def _count(conn: sqlite3.Connection, table: str) -> int:
    return conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]


class TestCheckStatement:
    def test_consistent_statement_has_no_problems(self) -> None:
        parsed = statement(
            row("2026-09-01", -1000, balance=9000),
            row("2026-09-02", 2500, balance=11500),
            opening=10000,
            closing=11500,
            period=("2026-09-01", "2026-09-30"),
        )
        assert check_statement(parsed) == []

    def test_balance_break_names_row_and_date_but_not_description(self) -> None:
        parsed = statement(
            row("2026-09-01", -1000, "PRIVATE MERCHANT", balance=9000),
            row("2026-09-02", -500, "PRIVATE MERCHANT", balance=8000),
        )
        problems = check_statement(parsed)
        assert len(problems) == 1
        assert "Row 2 (2026-09-02)" in problems[0]
        assert "PRIVATE" not in problems[0]

    def test_rows_without_a_printed_balance_are_carried(self) -> None:
        parsed = statement(
            row("2026-09-01", -1000, balance=9000),
            row("2026-09-01", -200),
            row("2026-09-01", -300, balance=8500),
        )
        assert check_statement(parsed) == []

    def test_opening_balance_mismatch(self) -> None:
        parsed = statement(row("2026-09-01", -1000, balance=8000), opening=10000)
        assert "Row 1" in check_statement(parsed)[0]

    def test_closing_balance_mismatch(self) -> None:
        parsed = statement(row("2026-09-01", -1000, balance=9000), closing=9500)
        assert "closing balance" in check_statement(parsed)[0]

    def test_empty_statement_with_moving_balance_is_inconsistent(self) -> None:
        assert check_statement(statement(opening=100, closing=200))
        assert check_statement(statement(opening=100, closing=100)) == []

    def test_rows_out_of_date_order(self) -> None:
        parsed = statement(row("2026-09-02", -100), row("2026-09-01", -100))
        assert "oldest first" in check_statement(parsed)[0]

    def test_row_in_another_currency(self) -> None:
        parsed = statement(row("2026-09-01", -100, currency="GBP"))
        assert "GBP" in check_statement(parsed)[0]

    def test_row_outside_stated_period(self) -> None:
        parsed = statement(row("2026-10-01", -100), period=("2026-09-01", "2026-09-30"))
        assert "outside the statement period" in check_statement(parsed)[0]


class TestIdentityKeys:
    def test_identical_rows_get_distinct_keys(self) -> None:
        coffee = row("2026-09-01", -350)
        first, second = identity_keys([coffee, coffee])
        assert first != second

    def test_keys_are_stable(self) -> None:
        rows = [row("2026-09-01", -350), row("2026-09-02", -100)]
        assert identity_keys(rows) == identity_keys(list(rows))

    def test_description_whitespace_does_not_change_identity(self) -> None:
        assert identity_keys(
            [row("2026-09-01", -350, "EXAMPLE  CAFE ")]
        ) == identity_keys([row("2026-09-01", -350, "EXAMPLE CAFE")])

    def test_printed_balance_is_part_of_identity(self) -> None:
        assert identity_keys([row("2026-09-01", -350, balance=100)]) != identity_keys(
            [row("2026-09-01", -350, balance=200)]
        )


class TestImportStatement:
    def test_writes_transactions_sightings_and_import(
        self, conn: sqlite3.Connection, account: Account, tmp_path: Path
    ) -> None:
        parsed = statement(
            row("2026-09-01", -1000, balance=9000),
            row("2026-09-02", -500, balance=8500),
        )
        result = _import(conn, account, parsed, tmp_path)
        assert (result.rows_seen, result.rows_new, result.already_imported) == (
            2,
            2,
            False,
        )
        assert _count(conn, "transactions") == 2
        assert _count(conn, "transaction_sightings") == 2
        stored = conn.execute("SELECT * FROM statement_imports").fetchone()
        assert (stored["rows_seen"], stored["rows_new"]) == (2, 2)
        assert stored["first_posted_on"] == "2026-09-01"

    def test_same_file_twice_is_a_no_op(
        self, conn: sqlite3.Connection, account: Account, tmp_path: Path
    ) -> None:
        parsed = statement(row("2026-09-01", -1000, balance=9000))
        first = _import(conn, account, parsed, tmp_path)
        second = _import(conn, account, parsed, tmp_path)
        assert second.already_imported
        assert second.import_id == first.import_id
        assert second.rows_new == 0
        assert _count(conn, "statement_imports") == 1
        assert _count(conn, "transactions") == 1

    def test_overlapping_statement_adds_only_new_rows(
        self, conn: sqlite3.Connection, account: Account, tmp_path: Path
    ) -> None:
        shared = row("2026-09-02", -500, balance=8500)
        _import(
            conn,
            account,
            statement(row("2026-09-01", -1000, balance=9000), shared),
            tmp_path,
            content=b"first",
        )
        result = _import(
            conn,
            account,
            statement(shared, row("2026-09-03", -500, balance=8000)),
            tmp_path,
            content=b"second",
        )
        assert result.rows_new == 1
        assert result.new_breaks == ()
        assert _count(conn, "transactions") == 3
        assert _count(conn, "transaction_sightings") == 4

    def test_identical_rows_on_one_day_are_both_kept(
        self, conn: sqlite3.Connection, account: Account, tmp_path: Path
    ) -> None:
        coffee = row("2026-09-01", -350)
        result = _import(conn, account, statement(coffee, coffee), tmp_path)
        assert result.rows_new == 2

    def test_rejected_statement_leaves_no_trace(
        self, conn: sqlite3.Connection, account: Account, tmp_path: Path
    ) -> None:
        parsed = statement(
            row("2026-09-01", -1000, balance=9000),
            row("2026-09-02", -500, balance=8000),
        )
        with pytest.raises(ImportRejected, match="nothing was written"):
            _import(conn, account, parsed, tmp_path)
        assert _count(conn, "statement_imports") == 0
        assert _count(conn, "transactions") == 0
        assert not (tmp_path / "sources").exists()

    def test_currency_must_match_account(
        self, conn: sqlite3.Connection, account: Account, tmp_path: Path
    ) -> None:
        parsed = statement(row("2026-09-01", -100, currency="GBP"), currency="GBP")
        with pytest.raises(ImportRejected, match="account 'test-current' is in EUR"):
            _import(conn, account, parsed, tmp_path)

    def test_another_parser_over_the_same_dates_is_refused(
        self, conn: sqlite3.Connection, account: Account, tmp_path: Path
    ) -> None:
        _import(
            conn, account, statement(row("2026-09-01", -100)), tmp_path, content=b"csv"
        )
        pdf = statement(row("2026-09-01", -100), parser="test-pdf")
        with pytest.raises(ImportRejected, match="test-csv v1"):
            _import(conn, account, pdf, tmp_path, content=b"pdf", name="statement.pdf")
        assert _count(conn, "transactions") == 1

    def test_another_parser_on_new_dates_is_allowed(
        self, conn: sqlite3.Connection, account: Account, tmp_path: Path
    ) -> None:
        _import(
            conn, account, statement(row("2026-09-01", -100)), tmp_path, content=b"csv"
        )
        later = statement(row("2026-10-01", -100), parser="test-pdf")
        assert _import(conn, account, later, tmp_path, content=b"pdf").rows_new == 1

    def test_gap_between_statements_is_reported(
        self, conn: sqlite3.Connection, account: Account, tmp_path: Path
    ) -> None:
        _import(
            conn, account, statement(row("2026-09-01", -1000, balance=9000)), tmp_path
        )
        later = statement(row("2026-09-10", -200, balance=8000))
        result = _import(conn, account, later, tmp_path, content=b"later")
        assert result.new_breaks == (BalanceBreak(date(2026, 9, 10), 8800, 8000),)

    def test_archive_is_private(
        self, conn: sqlite3.Connection, account: Account, tmp_path: Path
    ) -> None:
        result = _import(
            conn, account, statement(), tmp_path, content=b"bytes", name="X.CSV"
        )
        assert result.archive_path.name == "source.csv"
        assert result.archive_path.read_bytes() == b"bytes"
        assert stat.S_IMODE(result.archive_path.stat().st_mode) == 0o600
        assert stat.S_IMODE(result.archive_path.parent.stat().st_mode) == 0o700
        assert stat.S_IMODE(result.archive_path.parent.parent.stat().st_mode) == 0o700


class TestArchive:
    def test_repository_destination_is_refused(self) -> None:
        root = REPOSITORY_ROOT / "never-created-sources"
        with pytest.raises(ValueError, match="inside the repository"):
            archive_source(root, b"data", suffix=".csv")
        assert not root.exists()

    def test_unsafe_suffix_is_dropped(self, tmp_path: Path) -> None:
        _, path = archive_source(tmp_path, b"data", suffix=".c/sv")
        assert path.name == "source"

    def test_modified_archive_is_detected(self, tmp_path: Path) -> None:
        _, path = archive_source(tmp_path, b"data", suffix=".csv")
        path.chmod(0o600)
        path.write_bytes(b"tampered")
        with pytest.raises(ValueError, match="no longer matches"):
            archive_source(tmp_path, b"data", suffix=".csv")
