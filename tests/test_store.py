"""Store round trips, account validation and database opening rules."""

from __future__ import annotations

import sqlite3
import stat
from pathlib import Path

import pytest

from models import Account
from store import add_account, get_account, load_accounts, open_db, open_existing_db


def _account(**overrides: object) -> Account:
    values: dict[str, object] = {
        "name": "test-current",
        "institution": "Test Bank",
        "kind": "current",
        "currency": "EUR",
    }
    values.update(overrides)
    return Account(**values)  # type: ignore[arg-type]


class TestAccounts:
    def test_round_trip(self, conn: sqlite3.Connection) -> None:
        stored = add_account(conn, _account(identifier_hint="1234"))
        assert stored.id is not None
        assert load_accounts(conn) == [stored]
        assert get_account(conn, "test-current") == stored

    def test_duplicate_name_rejected(self, conn: sqlite3.Connection) -> None:
        add_account(conn, _account())
        with pytest.raises(ValueError, match="already exists"):
            add_account(conn, _account())

    def test_unknown_account_lists_known(
        self, conn: sqlite3.Connection, account: Account
    ) -> None:
        with pytest.raises(ValueError, match="Known: test-current"):
            get_account(conn, "missing")


class TestAccountValidation:
    @pytest.mark.parametrize(
        "overrides",
        [
            {"name": "AIB Current"},
            {"institution": "  "},
            {"kind": "brokerage"},
            {"currency": "eur"},
            {"identifier_hint": "IE29AIBK93115212345678"},
            {"identifier_hint": "123"},
        ],
    )
    def test_rejects_invalid_fields(self, overrides: dict[str, object]) -> None:
        with pytest.raises(ValueError):
            _account(**overrides)


class TestOpeningDatabases:
    def test_open_existing_refuses_to_create(self, tmp_path: Path) -> None:
        path = tmp_path / "ledger.db"
        with pytest.raises(FileNotFoundError, match="init"):
            open_existing_db(path)
        assert not path.exists()

    def test_open_db_creates_owner_only_file(self, tmp_path: Path) -> None:
        path = tmp_path / "ledger.db"
        open_db(path).close()
        assert stat.S_IMODE(path.stat().st_mode) == 0o600
