"""Account checks and dry-run previews."""

from __future__ import annotations

import sqlite3
from dataclasses import replace
from pathlib import Path

import pytest

from ingest import ImportRejected, import_statement, preview_import
from models import Account
from tests.factories import row, statement


def _count(conn: sqlite3.Connection, table: str) -> int:
    return conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]


class TestAccountHint:
    def test_file_for_another_account_is_refused(
        self, conn: sqlite3.Connection, account: Account, tmp_path: Path
    ) -> None:
        hinted = replace(account, identifier_hint="9999")
        parsed = replace(statement(row("2026-09-01", -100)), account_hint="1234")
        with pytest.raises(ImportRejected, match="ending 1234.*ends in 9999"):
            import_statement(
                conn,
                account=hinted,
                statement=parsed,
                content=b"x",
                source_name="x.csv",
                archive_root=tmp_path,
            )
        assert _count(conn, "transactions") == 0

    def test_account_without_a_hint_accepts_the_file(
        self, conn: sqlite3.Connection, account: Account, tmp_path: Path
    ) -> None:
        parsed = replace(statement(row("2026-09-01", -100)), account_hint="1234")
        result = import_statement(
            conn,
            account=account,
            statement=parsed,
            content=b"x",
            source_name="x.csv",
            archive_root=tmp_path,
        )
        assert result.rows_new == 1


class TestPreviewImport:
    def test_counts_new_and_known_rows_without_writing(
        self, conn: sqlite3.Connection, account: Account, tmp_path: Path
    ) -> None:
        shared = row("2026-09-01", -1000, balance=9000)
        import_statement(
            conn,
            account=account,
            statement=statement(shared),
            content=b"first",
            source_name="a.csv",
            archive_root=tmp_path,
        )
        preview = preview_import(
            conn,
            account=account,
            statement=statement(shared, row("2026-09-02", -500, balance=8500)),
            content=b"second",
        )
        assert (preview.rows_seen, preview.rows_new) == (2, 1)
        assert not preview.already_imported
        assert preview.problems == ()
        assert _count(conn, "statement_imports") == 1
        assert _count(conn, "transactions") == 1

    def test_flags_a_file_already_imported(
        self, conn: sqlite3.Connection, account: Account, tmp_path: Path
    ) -> None:
        parsed = statement(row("2026-09-01", -100))
        import_statement(
            conn,
            account=account,
            statement=parsed,
            content=b"same",
            source_name="a.csv",
            archive_root=tmp_path,
        )
        preview = preview_import(
            conn, account=account, statement=parsed, content=b"same"
        )
        assert preview.already_imported
        assert preview.rows_new == 0

    def test_returns_problems_instead_of_raising(
        self, conn: sqlite3.Connection, account: Account
    ) -> None:
        broken = statement(
            row("2026-09-01", -1000, balance=9000),
            row("2026-09-02", -500, balance=8000),
        )
        preview = preview_import(conn, account=account, statement=broken, content=b"x")
        assert len(preview.problems) == 1
        assert _count(conn, "statement_imports") == 0
