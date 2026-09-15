"""Facts derived from the ledger: running-balance checks and balances.

Nothing here is stored. A balance is recomputed from transactions every time,
so a corrected or newly imported row can never leave a stale figure behind.

Public API:
    running_balance_breaks -- walk amounts against printed balances
    balance_breaks         -- the same walk over an account's whole ledger
    latest_balance         -- an account's balance at its last transaction
    BalanceBreak           -- one place the walk failed

Example:
    from ledger import balance_breaks

    for gap in balance_breaks(conn, account.id):
        print(gap.day, gap.expected_minor, gap.found_minor)
"""

from __future__ import annotations

import sqlite3
from collections.abc import Iterable
from dataclasses import dataclass
from datetime import date

from store import load_ledger_rows


@dataclass(frozen=True)
class BalanceBreak:
    """A printed balance the preceding rows do not add up to.

    Attributes:
        day: Posting date of the row that printed the balance.
        expected_minor: Previous printed balance plus the rows since.
        found_minor: The balance actually printed.
    """

    day: date
    expected_minor: int
    found_minor: int


def running_balance_breaks(
    entries: Iterable[tuple[int, int | None]],
    *,
    opening: int | None = None,
) -> tuple[list[tuple[int, int, int]], int | None]:
    """Walk ``(amount, printed balance)`` pairs and report where they disagree.

    The walk starts from *opening*, or from the first printed balance when there
    is no opening. Rows without a printed balance are carried forward. After a
    disagreement it re-anchors on the printed balance, so one missing row is
    reported once rather than on every row that follows it.

    Args:
        entries: Amount and printed balance (or None) per row, in bank order.
        opening: Balance before the first row, when known.

    Returns:
        ``(breaks, final)`` where each break is ``(index, expected, found)``
        and *final* is the running balance after the last row, or None when no
        balance was ever known.
    """
    running = opening
    breaks: list[tuple[int, int, int]] = []
    for index, (amount, balance) in enumerate(entries):
        if running is not None:
            running += amount
        if balance is None:
            continue
        if running is not None and running != balance:
            breaks.append((index, running, balance))
        running = balance
    return breaks, running


def balance_breaks(conn: sqlite3.Connection, account_id: int) -> list[BalanceBreak]:
    """Walk an account's whole ledger in date order.

    Each statement is already consistent on its own, so a break here sits at
    a boundary between imports: rows missing between two statements, or an
    overlapping file that disagreed with an earlier one.

    Args:
        conn: Open ledger connection.
        account_id: Account to check.

    Returns:
        Every break, oldest first.
    """
    rows = load_ledger_rows(conn, account_id)
    found, _ = running_balance_breaks(
        (row["amount_minor"], row["balance_after_minor"]) for row in rows
    )
    return [
        BalanceBreak(date.fromisoformat(rows[index]["posted_on"]), expected, actual)
        for index, expected, actual in found
    ]


def latest_balance(
    conn: sqlite3.Connection, account_id: int
) -> tuple[date, int] | None:
    """Return the balance after an account's last transaction.

    Rows after the last printed balance are added to it.

    Returns:
        ``(date of last transaction, balance in minor units)``, or None when
        no statement ever printed a balance.
    """
    rows = load_ledger_rows(conn, account_id)
    _, final = running_balance_breaks(
        (row["amount_minor"], row["balance_after_minor"]) for row in rows
    )
    if final is None:
        return None
    return date.fromisoformat(rows[-1]["posted_on"]), final
