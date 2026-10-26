"""SQLite persistence for the ledger. No business logic.

Store functions never commit. The caller wraps a unit of work in ``with conn:``
so an import writes all of its rows or none of them.

Public API:
    connect_db         -- open a database, migrations optional
    open_db            -- open or create a database; only ``init`` calls it
    open_existing_db   -- open a database, refusing to create one
    add_account        -- insert an account, returning it with its id
    load_accounts      -- every account, by name
    get_account        -- one account by name
    find_import        -- an earlier import of the same file by the same parser
    insert_import      -- record one statement import
    set_import_rows_new -- record how many rows an import added
    insert_transaction -- insert a row unless its identity is already known
    insert_sighting    -- record that an import reported a transaction
    known_identity_keys -- which identity keys an account already holds
    load_description_inputs -- transactions with their raw fields and parser
    parsers_between    -- parsers that imported an account's rows in a range
    load_ledger_rows   -- an account's transactions in ledger order
    account_summary    -- counts and date coverage for one account
    table_counts       -- row counts for every ledger table
    add_document       -- insert a document, returning it with its id
    find_document      -- a document by content hash
    get_document       -- a document by id
    load_documents     -- every document, newest first
    load_imports       -- every statement import with its account
    set_account_identifiers -- store or replace an account's IBAN and BIC
    get_account_identifiers -- an account's IBAN and BIC, if entered

Example:
    from store import open_existing_db, load_accounts

    conn = open_existing_db(profile.db)
    accounts = load_accounts(conn)
"""

from __future__ import annotations

import json
import logging
import os
import sqlite3
from collections.abc import Sequence
from dataclasses import replace
from datetime import UTC, date, datetime
from pathlib import Path

from config import PRIVATE_DIR_MODE, PRIVATE_FILE_MODE
from db.migrations import apply_migrations
from identifiers import AccountIdentifiers
from models import Account, Document, ParsedStatement, StatementRow

logger = logging.getLogger(__name__)

LEDGER_TABLES: tuple[str, ...] = (
    "accounts",
    "statement_imports",
    "transactions",
    "transaction_sightings",
    "documents",
    "account_identifiers",
)


def _now() -> str:
    """Return the current UTC time as an ISO-8601 string."""
    return datetime.now(UTC).isoformat()


def connect_db(path: Path, *, migrate: bool = True) -> sqlite3.Connection:
    """Open or create the database at *path* and optionally migrate it.

    A newly created file is made owner-only before anything is written to it.

    Args:
        path: Filesystem path for the SQLite database file.
        migrate: Whether to apply pending migrations.

    Returns:
        An open connection with foreign keys enforced and WAL mode set.
    """
    path = path.expanduser().resolve()
    path.parent.mkdir(parents=True, exist_ok=True, mode=PRIVATE_DIR_MODE)
    created = not path.exists()
    conn = sqlite3.connect(str(path))
    if created:
        os.chmod(path, PRIVATE_FILE_MODE)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    conn.execute("PRAGMA journal_mode = WAL")
    if migrate:
        apply_migrations(conn)
    logger.debug("Opened database: %s", path)
    return conn


def open_db(path: Path) -> sqlite3.Connection:
    """Open or create the database at *path* and apply migrations.

    Creates the file when it is missing, so only ``init`` may call this.
    """
    return connect_db(path, migrate=True)


def open_existing_db(path: Path) -> sqlite3.Connection:
    """Open an existing database and apply pending migrations.

    ``sqlite3.connect`` silently creates an empty file, which would turn a
    wrong profile or ``FINCH_HOME`` into an empty ledger reporting no money
    rather than an error.

    Raises:
        FileNotFoundError: If no database exists at *path*.
    """
    resolved = path.expanduser().resolve()
    if not resolved.exists():
        raise FileNotFoundError(
            f"No database at {resolved}. Run 'uv run python main.py init' to create it."
        )
    return connect_db(resolved, migrate=True)


# ---------------------------------------------------------------------------
# Accounts
# ---------------------------------------------------------------------------


def _account(row: sqlite3.Row) -> Account:
    return Account(
        name=row["name"],
        institution=row["institution"],
        kind=row["kind"],
        currency=row["currency"],
        identifier_hint=row["identifier_hint"],
        id=row["id"],
    )


def add_account(conn: sqlite3.Connection, account: Account) -> Account:
    """Insert an account.

    Returns:
        The account with its database id.

    Raises:
        ValueError: If an account with that name already exists.
    """
    try:
        cursor = conn.execute(
            """
            INSERT INTO accounts (name, institution, kind, currency, identifier_hint, created_at)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (
                account.name,
                account.institution,
                account.kind,
                account.currency,
                account.identifier_hint,
                _now(),
            ),
        )
    except sqlite3.IntegrityError as exc:
        raise ValueError(f"An account named {account.name!r} already exists.") from exc
    return replace(account, id=cursor.lastrowid)


def load_accounts(conn: sqlite3.Connection) -> list[Account]:
    """Return every account, ordered by name."""
    rows = conn.execute("SELECT * FROM accounts ORDER BY name").fetchall()
    return [_account(row) for row in rows]


def get_account(conn: sqlite3.Connection, name: str) -> Account:
    """Return one account by name.

    Raises:
        ValueError: If no account has that name; the message lists known ones.
    """
    row = conn.execute("SELECT * FROM accounts WHERE name = ?", (name,)).fetchone()
    if row is None:
        known = ", ".join(account.name for account in load_accounts(conn)) or "none"
        raise ValueError(
            f"No account named {name!r}. Known: {known}. Add one with "
            f"'uv run python main.py account add'."
        )
    return _account(row)


# ---------------------------------------------------------------------------
# Imports and transactions
# ---------------------------------------------------------------------------


def find_import(
    conn: sqlite3.Connection,
    *,
    account_id: int,
    sha256: str,
    parser: str,
    parser_version: int,
) -> sqlite3.Row | None:
    """Return an earlier import of the same bytes by the same parser, if any."""
    return conn.execute(
        """
        SELECT * FROM statement_imports
        WHERE account_id = ? AND source_sha256 = ? AND parser = ? AND parser_version = ?
        """,
        (account_id, sha256, parser, parser_version),
    ).fetchone()


def insert_import(
    conn: sqlite3.Connection,
    *,
    account_id: int,
    sha256: str,
    source_name: str,
    statement: ParsedStatement,
) -> int:
    """Record one statement import with zero new rows; returns its id."""
    rows = statement.rows
    cursor = conn.execute(
        """
        INSERT INTO statement_imports (
            account_id, source_sha256, source_name, parser, parser_version,
            period_start, period_end, opening_balance_minor, closing_balance_minor,
            first_posted_on, last_posted_on, rows_seen, rows_new, imported_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 0, ?)
        """,
        (
            account_id,
            sha256,
            source_name,
            statement.parser,
            statement.parser_version,
            statement.period_start.isoformat() if statement.period_start else None,
            statement.period_end.isoformat() if statement.period_end else None,
            statement.opening_balance_minor,
            statement.closing_balance_minor,
            rows[0].posted_on.isoformat() if rows else None,
            rows[-1].posted_on.isoformat() if rows else None,
            len(rows),
            _now(),
        ),
    )
    return int(cursor.lastrowid)


def set_import_rows_new(
    conn: sqlite3.Connection, import_id: int, rows_new: int
) -> None:
    """Record how many transactions an import added."""
    conn.execute(
        "UPDATE statement_imports SET rows_new = ? WHERE id = ?", (rows_new, import_id)
    )


def insert_transaction(
    conn: sqlite3.Connection,
    *,
    account_id: int,
    identity_key: str,
    row: StatementRow,
    import_id: int,
) -> tuple[int, bool]:
    """Insert a transaction unless one with the same identity exists.

    Returns:
        ``(transaction id, whether it was newly inserted)``.
    """
    cursor = conn.execute(
        """
        INSERT INTO transactions (
            account_id, identity_key, posted_on, amount_minor, currency,
            description, balance_after_minor, bank_reference, raw_json,
            first_import_id, created_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT (account_id, identity_key) DO NOTHING
        """,
        (
            account_id,
            identity_key,
            row.posted_on.isoformat(),
            row.amount_minor,
            row.currency,
            row.description,
            row.balance_after_minor,
            row.bank_reference,
            json.dumps(row.raw, sort_keys=True, ensure_ascii=False),
            import_id,
            _now(),
        ),
    )
    if cursor.rowcount == 1:
        return int(cursor.lastrowid), True
    existing = conn.execute(
        "SELECT id FROM transactions WHERE account_id = ? AND identity_key = ?",
        (account_id, identity_key),
    ).fetchone()
    return int(existing["id"]), False


def insert_sighting(
    conn: sqlite3.Connection, *, transaction_id: int, import_id: int, row_number: int
) -> None:
    """Record that an import reported a transaction at a given row."""
    conn.execute(
        "INSERT INTO transaction_sightings (transaction_id, import_id, row_number) "
        "VALUES (?, ?, ?)",
        (transaction_id, import_id, row_number),
    )


def parsers_between(
    conn: sqlite3.Connection, account_id: int, start: str, end: str
) -> set[tuple[str, int]]:
    """Return the parsers that first imported an account's rows in a date range."""
    rows = conn.execute(
        """
        SELECT DISTINCT i.parser, i.parser_version
        FROM transactions t
        JOIN statement_imports i ON i.id = t.first_import_id
        WHERE t.account_id = ? AND t.posted_on BETWEEN ? AND ?
        """,
        (account_id, start, end),
    ).fetchall()
    return {(row["parser"], row["parser_version"]) for row in rows}


def load_ledger_rows(conn: sqlite3.Connection, account_id: int) -> list[sqlite3.Row]:
    """Return an account's transactions by posting date, then insertion order.

    Insertion order is file order within an import, which is the bank's order.
    """
    return conn.execute(
        """
        SELECT id, posted_on, amount_minor, balance_after_minor
        FROM transactions
        WHERE account_id = ?
        ORDER BY posted_on, id
        """,
        (account_id,),
    ).fetchall()


def account_summary(conn: sqlite3.Connection, account_id: int) -> sqlite3.Row:
    """Return transaction count, first and last posting date, and import count."""
    return conn.execute(
        """
        SELECT
            (SELECT COUNT(*) FROM transactions WHERE account_id = :id) AS transactions,
            (SELECT MIN(posted_on) FROM transactions WHERE account_id = :id) AS first_posted_on,
            (SELECT MAX(posted_on) FROM transactions WHERE account_id = :id) AS last_posted_on,
            (SELECT COUNT(*) FROM statement_imports WHERE account_id = :id) AS imports
        """,
        {"id": account_id},
    ).fetchone()


def table_counts(conn: sqlite3.Connection) -> dict[str, int]:
    """Return row counts for every ledger table."""
    return {
        table: conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
        for table in LEDGER_TABLES
    }


_KEY_BATCH = 500
"""Identity keys per ``IN (...)`` query, well under SQLite's bound-parameter limit."""


def known_identity_keys(
    conn: sqlite3.Connection, account_id: int, keys: Sequence[str]
) -> set[str]:
    """Return which of *keys* are already stored for an account."""
    known: set[str] = set()
    for start in range(0, len(keys), _KEY_BATCH):
        batch = keys[start : start + _KEY_BATCH]
        placeholders = ", ".join("?" * len(batch))
        rows = conn.execute(
            f"SELECT identity_key FROM transactions "
            f"WHERE account_id = ? AND identity_key IN ({placeholders})",
            (account_id, *batch),
        ).fetchall()
        known.update(row["identity_key"] for row in rows)
    return known


def load_description_inputs(
    conn: sqlite3.Connection, account_id: int
) -> list[sqlite3.Row]:
    """Return an account's transactions with the parser that first read each."""
    return conn.execute(
        """
        SELECT t.id, t.posted_on, t.amount_minor, t.description, t.raw_json, i.parser
        FROM transactions t
        JOIN statement_imports i ON i.id = t.first_import_id
        WHERE t.account_id = ?
        ORDER BY t.posted_on, t.id
        """,
        (account_id,),
    ).fetchall()


# ---------------------------------------------------------------------------
# Documents
# ---------------------------------------------------------------------------


def _document(row: sqlite3.Row) -> Document:
    return Document(
        sha256=row["sha256"],
        original_name=row["original_name"],
        title=row["title"],
        dated_on=date.fromisoformat(row["dated_on"]) if row["dated_on"] else None,
        note=row["note"],
        id=row["id"],
    )


def add_document(conn: sqlite3.Connection, document: Document) -> Document:
    """Insert a document.

    Returns:
        The document with its database id.

    Raises:
        ValueError: If a document with the same content is already stored.
    """
    try:
        cursor = conn.execute(
            """
            INSERT INTO documents (sha256, original_name, title, dated_on, note, added_at)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (
                document.sha256,
                document.original_name,
                document.title,
                document.dated_on.isoformat() if document.dated_on else None,
                document.note,
                _now(),
            ),
        )
    except sqlite3.IntegrityError as exc:
        raise ValueError("This file is already kept as a document.") from exc
    return replace(document, id=cursor.lastrowid)


def find_document(conn: sqlite3.Connection, sha256: str) -> Document | None:
    """Return the document with this content hash, if any."""
    row = conn.execute("SELECT * FROM documents WHERE sha256 = ?", (sha256,)).fetchone()
    return _document(row) if row else None


def get_document(conn: sqlite3.Connection, document_id: int) -> Document:
    """Return one document by id.

    Raises:
        ValueError: If no document has that id.
    """
    row = conn.execute(
        "SELECT * FROM documents WHERE id = ?", (document_id,)
    ).fetchone()
    if row is None:
        raise ValueError(
            f"No document #{document_id}. List them with 'uv run python main.py doc list'."
        )
    return _document(row)


def load_documents(conn: sqlite3.Connection) -> list[Document]:
    """Return every document, newest first by its own date, then by when added."""
    rows = conn.execute(
        "SELECT * FROM documents ORDER BY COALESCE(dated_on, added_at) DESC, id DESC"
    ).fetchall()
    return [_document(row) for row in rows]


def load_imports(conn: sqlite3.Connection) -> list[sqlite3.Row]:
    """Return every statement import with its account's name, newest first."""
    return conn.execute(
        """
        SELECT i.id, i.source_sha256, i.first_posted_on, i.last_posted_on,
               i.rows_seen, i.imported_at, a.name AS account, a.institution
        FROM statement_imports i
        JOIN accounts a ON a.id = i.account_id
        ORDER BY i.last_posted_on DESC, i.id DESC
        """
    ).fetchall()


# ---------------------------------------------------------------------------
# Account identifiers
# ---------------------------------------------------------------------------


def set_account_identifiers(
    conn: sqlite3.Connection, account_id: int, identifiers: AccountIdentifiers
) -> None:
    """Store an account's IBAN and BIC, replacing any entered before."""
    conn.execute(
        """
        INSERT INTO account_identifiers (account_id, iban, bic, updated_at)
        VALUES (?, ?, ?, ?)
        ON CONFLICT (account_id) DO UPDATE SET
            iban = excluded.iban, bic = excluded.bic, updated_at = excluded.updated_at
        """,
        (account_id, identifiers.iban, identifiers.bic, _now()),
    )


def get_account_identifiers(
    conn: sqlite3.Connection, account_id: int
) -> AccountIdentifiers | None:
    """Return an account's IBAN and BIC, or None if none were entered."""
    row = conn.execute(
        "SELECT iban, bic FROM account_identifiers WHERE account_id = ?",
        (account_id,),
    ).fetchone()
    return AccountIdentifiers(iban=row["iban"], bic=row["bic"]) if row else None
