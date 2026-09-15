"""Accounts, statement imports, and the transactions statements reported."""

from __future__ import annotations

import sqlite3

NAME = "ledger"


def upgrade(conn: sqlite3.Connection) -> None:
    """Create the ledger.

    ``transactions`` holds what a bank said and nothing else. Interpretations —
    which merchant, which category, that two rows are one transfer — will get
    their own tables with their own provenance, because they are opinions that
    get corrected, and a correction must never overwrite the evidence it
    corrects. No such table exists yet; each arrives with the code that fills
    it, so its shape is decided by real data rather than guessed here.

    Money is INTEGER minor units. Imports are checked against the bank's running
    balance to the cent, which REAL cannot promise.

    Banks export no transaction id. ``identity_key`` is derived from the printed
    fields plus an ordinal for otherwise identical rows, and is what makes an
    overlapping re-import add only what is new; ``ingest.identity_keys`` owns
    the recipe.

    ``transaction_sightings`` records every import that reported a row, not
    just the first, so any figure can be traced to the files that support it.

    There is no pending/settled status: statements contain settled rows only.
    It arrives with the first source that reports pending ones.
    """
    conn.executescript(
        """
        CREATE TABLE accounts (
            id               INTEGER PRIMARY KEY,
            name             TEXT NOT NULL UNIQUE,
            institution      TEXT NOT NULL,
            kind             TEXT NOT NULL CHECK (kind IN (
                                 'current', 'savings', 'credit_card', 'loan'
                             )),
            currency         TEXT NOT NULL,
            -- Last four digits at most. Never an IBAN or a full number.
            identifier_hint  TEXT,
            created_at       TEXT NOT NULL
        );

        CREATE TABLE statement_imports (
            id                     INTEGER PRIMARY KEY,
            account_id             INTEGER NOT NULL REFERENCES accounts(id),
            source_sha256          TEXT NOT NULL,
            source_name            TEXT NOT NULL,
            parser                 TEXT NOT NULL,
            parser_version         INTEGER NOT NULL,
            period_start           TEXT,
            period_end             TEXT,
            opening_balance_minor  INTEGER,
            closing_balance_minor  INTEGER,
            first_posted_on        TEXT,
            last_posted_on         TEXT,
            rows_seen              INTEGER NOT NULL,
            rows_new               INTEGER NOT NULL,
            imported_at            TEXT NOT NULL,
            UNIQUE (account_id, source_sha256, parser, parser_version)
        );

        CREATE TABLE transactions (
            id                   INTEGER PRIMARY KEY,
            account_id           INTEGER NOT NULL REFERENCES accounts(id),
            identity_key         TEXT NOT NULL,
            posted_on            TEXT NOT NULL,
            amount_minor         INTEGER NOT NULL,
            currency             TEXT NOT NULL,
            description          TEXT NOT NULL,
            balance_after_minor  INTEGER,
            bank_reference       TEXT,
            raw_json             TEXT NOT NULL,
            first_import_id      INTEGER NOT NULL REFERENCES statement_imports(id),
            created_at           TEXT NOT NULL,
            UNIQUE (account_id, identity_key)
        );

        CREATE INDEX transactions_account_date
            ON transactions(account_id, posted_on);

        CREATE TABLE transaction_sightings (
            transaction_id  INTEGER NOT NULL REFERENCES transactions(id),
            import_id       INTEGER NOT NULL REFERENCES statement_imports(id),
            row_number      INTEGER NOT NULL,
            PRIMARY KEY (transaction_id, import_id)
        );
        """
    )
