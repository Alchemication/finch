"""The owner's own IBAN and BIC for each account, typed in by hand."""

from __future__ import annotations

import sqlite3

NAME = "account identifiers"


def upgrade(conn: sqlite3.Connection) -> None:
    """Create ``account_identifiers``, at most one row per account.

    Transactions keep at most the last four digits of any account number;
    that rule is about bank rows, which are evidence. This table is the one
    place a full identifier lives: the owner's own, entered with
    ``account details``, so they can look it up later. It is kept apart from
    ``accounts`` so a model's read-only SQL can be denied this one table
    without losing the account list. The sort code and account number are not
    stored, since an Irish or UK IBAN contains both.
    """
    conn.executescript(
        """
        CREATE TABLE account_identifiers (
            account_id  INTEGER PRIMARY KEY REFERENCES accounts(id),
            iban        TEXT NOT NULL,
            bic         TEXT,
            updated_at  TEXT NOT NULL
        );
        """
    )
