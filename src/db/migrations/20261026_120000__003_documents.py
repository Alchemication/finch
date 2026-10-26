"""Documents kept beside the statements: contracts, letters, agreements."""

from __future__ import annotations

import sqlite3

NAME = "documents"


def upgrade(conn: sqlite3.Connection) -> None:
    """Create ``documents``, one row per archived file that is not a statement.

    The file itself lives in the same write-once archive as statements,
    ``sources/<sha256>/``, so every file a profile was given is in one place
    and found by its hash. This table adds what a person needs to find it
    again: a title, the date the document carries, and a note. Nothing here
    is parsed or computed from the file.

    ``original_name`` is kept for recognition only and never reused on disk,
    as for statements.
    """
    conn.executescript(
        """
        CREATE TABLE documents (
            id             INTEGER PRIMARY KEY,
            sha256         TEXT NOT NULL UNIQUE,
            original_name  TEXT NOT NULL,
            title          TEXT NOT NULL,
            dated_on       TEXT,
            note           TEXT,
            added_at       TEXT NOT NULL
        );
        """
    )
