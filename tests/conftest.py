"""Shared fixtures for finch tests."""

from __future__ import annotations

import sqlite3
from collections.abc import Iterator

import pytest

from db.migrations import apply_migrations
from models import Account
from store import add_account


@pytest.fixture
def conn() -> Iterator[sqlite3.Connection]:
    """An in-memory database with the full schema applied."""
    connection = sqlite3.connect(":memory:")
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA foreign_keys = ON")
    apply_migrations(connection)
    yield connection
    connection.close()


@pytest.fixture
def account(conn: sqlite3.Connection) -> Account:
    """One stored EUR current account."""
    return add_account(
        conn,
        Account(
            name="test-current", institution="Test Bank", kind="current", currency="EUR"
        ),
    )
