"""Turning a parsed statement into ledger rows, or refusing to.

Parsers read a bank format into a ``ParsedStatement``; this module decides
whether it may land. A statement that does not reconcile with itself writes
nothing. A misread column produces figures that look entirely plausible, and
the bank's own running balance is the one independent check available on every
row, so it is applied before anything is stored.

Public API:
    check_statement  -- every internal inconsistency in a statement
    identity_keys    -- stable per-row identity for idempotent re-imports
    preflight        -- every reason a statement may not land in an account
    preview_import   -- what an import would do, writing nothing
    import_statement -- validate, archive and write one statement
    ImportPreview    -- what an import would do
    ImportResult     -- what an import did
    ImportRejected   -- the statement may not land; ``problems`` says why

Example:
    from ingest import import_statement

    result = import_statement(
        conn, account=account, statement=parsed, content=data,
        source_name="export.csv", archive_root=profile.sources,
    )
"""

from __future__ import annotations

import hashlib
import logging
import sqlite3
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path

import store
from config import IMPORT_PROBLEMS_SHOWN
from ledger import BalanceBreak, balance_breaks, running_balance_breaks
from models import Account, ParsedStatement, StatementRow
from money import format_minor
from sources import archive_source

logger = logging.getLogger(__name__)

_KEY_SEPARATOR = "\x1f"


class ImportRejected(ValueError):
    """A statement may not land. Problems name rows by number and date only.

    Descriptions are left out on purpose: messages reach terminals and logs,
    and a merchant name is personal data.
    """

    def __init__(self, problems: list[str]) -> None:
        self.problems = problems
        shown = problems[:IMPORT_PROBLEMS_SHOWN]
        more = len(problems) - len(shown)
        lines = "\n".join(f"  - {problem}" for problem in shown)
        suffix = f"\n  ...and {more} more." if more else ""
        super().__init__(f"Statement rejected; nothing was written.\n{lines}{suffix}")


@dataclass(frozen=True)
class ImportPreview:
    """What an import would do.

    Attributes:
        rows_seen: Rows in the statement.
        rows_new: Rows not already in the ledger.
        already_imported: The same bytes were imported by the same parser.
        problems: Every reason the import would be rejected; empty when it
            would land.
    """

    rows_seen: int
    rows_new: int
    already_imported: bool
    problems: tuple[str, ...]


@dataclass(frozen=True)
class ImportResult:
    """What one import did.

    Attributes:
        import_id: The import row, or the earlier one for a repeated file.
        rows_seen: Rows in the statement.
        rows_new: Rows not already in the ledger.
        already_imported: The same bytes were imported by the same parser.
        archive_path: Where the file is archived.
        new_breaks: Ledger balance breaks that appeared with this import,
            usually rows missing between this statement and its neighbour.
    """

    import_id: int
    rows_seen: int
    rows_new: int
    already_imported: bool
    archive_path: Path
    new_breaks: tuple[BalanceBreak, ...] = ()


def check_statement(statement: ParsedStatement) -> list[str]:
    """Return every internal inconsistency in a statement.

    Checks rows are in date order, inside the stated period and in the stated
    currency, that each printed balance equals the previous one plus the rows
    since, and that the rows walk from the opening to the closing balance.

    Args:
        statement: Parser output.

    Returns:
        Human-readable problems; empty when the statement is consistent.
    """
    problems: list[str] = []
    rows = statement.rows
    currency = statement.currency
    start, end = statement.period_start, statement.period_end

    for number, row in enumerate(rows, start=1):
        where = f"Row {number} ({row.posted_on})"
        if row.currency != currency:
            problems.append(
                f"{where} is in {row.currency}, but the statement is in {currency}."
            )
        if number > 1 and row.posted_on < rows[number - 2].posted_on:
            problems.append(
                f"{where} is dated before the row above it; parsers must return rows oldest first."
            )
        if (start and row.posted_on < start) or (end and row.posted_on > end):
            problems.append(
                f"{where} falls outside the statement period {start} to {end}."
            )

    breaks, final = running_balance_breaks(
        ((row.amount_minor, row.balance_after_minor) for row in rows),
        opening=statement.opening_balance_minor,
    )
    for index, expected, found in breaks:
        problems.append(
            f"Row {index + 1} ({rows[index].posted_on}) prints a balance of "
            f"{format_minor(found, currency)}, but the balance before it plus the "
            f"rows since come to {format_minor(expected, currency)}."
        )

    closing = statement.closing_balance_minor
    if closing is not None and final is not None and final != closing:
        problems.append(
            f"The rows end at {format_minor(final, currency)}, but the statement's "
            f"closing balance is {format_minor(closing, currency)}."
        )
    return problems


def identity_keys(rows: Sequence[StatementRow]) -> list[str]:
    """Derive a stable identity for each row.

    Banks export no transaction id, so identity hashes the printed date,
    amount, currency, whitespace-normalised description and printed balance,
    plus an ordinal among rows that are otherwise identical in this file. The
    ordinal keeps two identical coffees on one day as two transactions.

    An overlapping statement reproduces the same keys for the rows it shares
    with an earlier one, provided both contain whole days, which monthly
    statements and date-range exports do.

    Args:
        rows: Statement rows in bank order.

    Returns:
        One hex key per row, in the same order.
    """
    seen: dict[str, int] = {}
    keys: list[str] = []
    for row in rows:
        base = _KEY_SEPARATOR.join(
            (
                row.posted_on.isoformat(),
                str(row.amount_minor),
                row.currency,
                " ".join(row.description.split()),
                "" if row.balance_after_minor is None else str(row.balance_after_minor),
            )
        )
        ordinal = seen.get(base, 0)
        seen[base] = ordinal + 1
        keys.append(
            hashlib.sha256(f"{base}{_KEY_SEPARATOR}{ordinal}".encode()).hexdigest()
        )
    return keys


def _require_stored(account: Account) -> int:
    """Return the account's id, refusing an account that was never stored."""
    if account.id is None:
        raise ValueError("Store the account before importing into it.")
    return account.id


def preflight(
    conn: sqlite3.Connection, account: Account, statement: ParsedStatement
) -> list[str]:
    """Return every reason *statement* may not land in *account*.

    Covers the statement's own consistency, that it belongs to this account
    and is in its currency, and that no other parser already imported its
    dates. Reads the database; writes nothing.

    Args:
        conn: Open ledger connection.
        account: Stored account the statement is meant for.
        statement: Parser output.

    Returns:
        Human-readable problems; empty when the statement may land.
    """
    account_id = _require_stored(account)
    problems: list[str] = []
    if statement.currency != account.currency:
        problems.append(
            f"The statement is in {statement.currency}, but account "
            f"{account.name!r} is in {account.currency}."
        )
    hint, expected = statement.account_hint, account.identifier_hint
    if hint and expected and hint != expected:
        problems.append(
            f"The file is for an account ending {hint}, but account "
            f"{account.name!r} ends in {expected}."
        )
    problems.extend(check_statement(statement))

    if statement.rows:
        first = statement.rows[0].posted_on
        last = statement.rows[-1].posted_on
        others = store.parsers_between(
            conn, account_id, first.isoformat(), last.isoformat()
        ) - {(statement.parser, statement.parser_version)}
        if others:
            names = ", ".join(
                f"{parser} v{version}" for parser, version in sorted(others)
            )
            problems.append(
                f"Transactions between {first} and {last} were already imported "
                f"with {names}. Parsers derive row identity differently, so "
                f"importing the same dates with {statement.parser} "
                f"v{statement.parser_version} would count them twice. Import "
                f"these dates in the format used before."
            )
    return problems


def preview_import(
    conn: sqlite3.Connection,
    *,
    account: Account,
    statement: ParsedStatement,
    content: bytes,
) -> ImportPreview:
    """Report what importing *statement* would do, writing nothing.

    Args:
        conn: Open ledger connection.
        account: Stored account the statement is meant for.
        statement: Parser output for *content*.
        content: The original file's bytes.

    Returns:
        Row counts and every problem that would reject the import.
    """
    account_id = _require_stored(account)
    problems = preflight(conn, account, statement)
    earlier = store.find_import(
        conn,
        account_id=account_id,
        sha256=hashlib.sha256(content).hexdigest(),
        parser=statement.parser,
        parser_version=statement.parser_version,
    )
    keys = identity_keys(statement.rows)
    known = store.known_identity_keys(conn, account_id, keys)
    return ImportPreview(
        rows_seen=len(keys),
        rows_new=sum(1 for key in keys if key not in known),
        already_imported=earlier is not None,
        problems=tuple(problems),
    )


def import_statement(
    conn: sqlite3.Connection,
    *,
    account: Account,
    statement: ParsedStatement,
    content: bytes,
    source_name: str,
    archive_root: Path,
) -> ImportResult:
    """Validate, archive and write one statement.

    Every check runs before the file is archived, and the rows are written in
    one transaction, so a rejected statement leaves no trace.

    Args:
        conn: Open ledger connection.
        account: Stored account the statement belongs to.
        statement: Parser output for *content*.
        content: The original file's bytes.
        source_name: The original filename, recorded on the import row.
        archive_root: The profile's sources directory.

    Returns:
        What the import did.

    Raises:
        ImportRejected: If :func:`preflight` finds any problem.
        ValueError: If the account has not been stored.
    """
    account_id = _require_stored(account)
    problems = preflight(conn, account, statement)
    if problems:
        raise ImportRejected(problems)

    suffix = Path(source_name).suffix
    digest = hashlib.sha256(content).hexdigest()
    earlier = store.find_import(
        conn,
        account_id=account_id,
        sha256=digest,
        parser=statement.parser,
        parser_version=statement.parser_version,
    )
    if earlier is not None:
        _, archive_path = archive_source(archive_root, content, suffix=suffix)
        return ImportResult(
            import_id=earlier["id"],
            rows_seen=len(statement.rows),
            rows_new=0,
            already_imported=True,
            archive_path=archive_path,
        )

    breaks_before = set(balance_breaks(conn, account_id))
    _, archive_path = archive_source(archive_root, content, suffix=suffix)
    keys = identity_keys(statement.rows)

    with conn:
        import_id = store.insert_import(
            conn,
            account_id=account_id,
            sha256=digest,
            source_name=Path(source_name).name,
            statement=statement,
        )
        rows_new = 0
        for number, (row, key) in enumerate(
            zip(statement.rows, keys, strict=True), start=1
        ):
            transaction_id, created = store.insert_transaction(
                conn,
                account_id=account_id,
                identity_key=key,
                row=row,
                import_id=import_id,
            )
            store.insert_sighting(
                conn,
                transaction_id=transaction_id,
                import_id=import_id,
                row_number=number,
            )
            rows_new += created
        store.set_import_rows_new(conn, import_id, rows_new)

    new_breaks = tuple(
        found
        for found in balance_breaks(conn, account_id)
        if found not in breaks_before
    )
    logger.info(
        "Imported %d new of %d rows into %s",
        rows_new,
        len(statement.rows),
        account.name,
    )
    return ImportResult(
        import_id=import_id,
        rows_seen=len(statement.rows),
        rows_new=rows_new,
        already_imported=False,
        archive_path=archive_path,
        new_breaks=new_breaks,
    )
