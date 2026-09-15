"""Schema migrations."""

from __future__ import annotations

import json
import sqlite3

import pytest

from db.migrations import apply_migrations, discover_migrations, list_migrations
from models import ACCOUNT_KINDS
from store import LEDGER_TABLES


class TestMigrations:
    def test_second_apply_is_a_no_op(self, conn: sqlite3.Connection) -> None:
        assert apply_migrations(conn) == []

    def test_every_migration_is_recorded(self, conn: sqlite3.Connection) -> None:
        assert all(status.status == "applied" for status in list_migrations(conn))

    def test_ledger_tables_exist(self, conn: sqlite3.Connection) -> None:
        names = {
            row[0]
            for row in conn.execute(
                "SELECT name FROM sqlite_master WHERE type = 'table'"
            )
        }
        assert set(LEDGER_TABLES) <= names

    def test_account_kind_constraint_matches_model(
        self, conn: sqlite3.Connection
    ) -> None:
        for index, kind in enumerate(ACCOUNT_KINDS):
            conn.execute(
                "INSERT INTO accounts (name, institution, kind, currency, created_at) "
                "VALUES (?, 'Bank', ?, 'EUR', 'now')",
                (f"a{index}", kind),
            )
        with pytest.raises(sqlite3.IntegrityError):
            conn.execute(
                "INSERT INTO accounts (name, institution, kind, currency, created_at) "
                "VALUES ('bogus', 'Bank', 'brokerage', 'EUR', 'now')"
            )


class TestMaskAccountNumbers:
    def test_masks_account_numbers_in_existing_raw_fields(self) -> None:
        connection = sqlite3.connect(":memory:")
        migrations = discover_migrations()
        migrations[0].upgrade(connection)
        connection.execute(
            "INSERT INTO accounts (id, name, institution, kind, currency, created_at) "
            "VALUES (1, 'a', 'Bank', 'current', 'EUR', 'now')"
        )
        connection.execute(
            "INSERT INTO statement_imports (id, account_id, source_sha256, source_name, parser, "
            "parser_version, rows_seen, rows_new, imported_at) "
            "VALUES (1, 1, 'x', 'x.csv', 'aib-csv', 1, 1, 1, 'now')"
        )
        raw = {"Description1": "FEE-QTR TO 28FEB25", "Description2": "987650-55501234"}
        connection.execute(
            "INSERT INTO transactions (id, account_id, identity_key, posted_on, amount_minor, "
            "currency, description, raw_json, first_import_id, created_at) "
            "VALUES (1, 1, 'k', '2025-03-28', -2800, 'EUR', 'FEE-QTR TO 28FEB25', ?, 1, 'now')",
            (json.dumps(raw),),
        )
        [mask] = [m for m in migrations if "mask_account_numbers" in m.key]
        mask.upgrade(connection)
        stored = json.loads(
            connection.execute("SELECT raw_json FROM transactions").fetchone()[0]
        )
        assert stored == {
            "Description1": "FEE-QTR TO 28FEB25",
            "Description2": "****1234",
        }
