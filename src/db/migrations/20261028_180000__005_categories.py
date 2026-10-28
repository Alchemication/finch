"""Category rules per counterparty, and labels for single transactions."""

from __future__ import annotations

import sqlite3

NAME = "categories"


def upgrade(conn: sqlite3.Connection) -> None:
    """Create ``category_rules`` and ``transaction_labels``.

    A category is an interpretation, so it never touches ``transactions``.
    Each transaction's category is worked out on every read: its label if it
    has one, else the confirmed rule for its counterparty key, else its
    channel's default, else unclassified.

    ``category_rules`` holds one row per decision about a counterparty key. A
    model proposes (``source = 'claude'``, ``status = 'proposed'``, with a
    confidence); the owner confirms, corrects or rejects, and that decision is
    a new ``owner`` row that supersedes the proposal rather than editing it, so
    history shows what was proposed and what was decided. Only confirmed rows
    apply. A rejected row has no category: the key stays unclassified even if
    its channel has a default. At most one row per key is active.

    ``transaction_labels`` is the owner's category for one transaction, for
    rows no counterparty rule can name: a transfer whose reference is typed per
    payment, or one payment unlike the rest from the same payee. A label wins
    over any rule, and is superseded the same way.

    Category slugs are validated in code (``categories.CATEGORIES``), not by a
    CHECK constraint, because the list is expected to change as it is used.
    """
    conn.executescript(
        """
        CREATE TABLE category_rules (
            id               INTEGER PRIMARY KEY,
            counterparty_key TEXT NOT NULL,
            category         TEXT,
            source           TEXT NOT NULL CHECK (source IN ('owner', 'claude')),
            status           TEXT NOT NULL CHECK (status IN (
                                 'proposed', 'confirmed', 'rejected'
                             )),
            confidence       TEXT CHECK (confidence IN ('high', 'medium', 'low')),
            note             TEXT,
            created_at       TEXT NOT NULL,
            superseded_by    INTEGER REFERENCES category_rules(id),
            CHECK ((status = 'rejected') = (category IS NULL))
        );
        CREATE UNIQUE INDEX category_rules_active
            ON category_rules (counterparty_key) WHERE superseded_by IS NULL;

        CREATE TABLE transaction_labels (
            id              INTEGER PRIMARY KEY,
            transaction_id  INTEGER NOT NULL REFERENCES transactions(id),
            category        TEXT,
            note            TEXT,
            created_at      TEXT NOT NULL,
            superseded_by   INTEGER REFERENCES transaction_labels(id)
        );
        CREATE UNIQUE INDEX transaction_labels_active
            ON transaction_labels (transaction_id) WHERE superseded_by IS NULL;
        """
    )
