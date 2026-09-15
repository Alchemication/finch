"""What each transaction is, as far as the bank's own text says.

Each bank's parser module may expose ``describe``, which reads its layout's
prefixes and columns into a channel, a counterparty and a foreign price. This
module applies it to stored rows and adds a grouping key. Nothing is stored:
improving a rule changes every past row at once, with no rebuild.

Public API:
    counterparty_key -- a grouping key robust to references and punctuation
    describe_account -- every transaction of an account, described

Example:
    from describe import describe_account

    rows = describe_account(conn, account.id)
"""

from __future__ import annotations

import json
import re
import sqlite3
from datetime import date

from models import BankDescription, DescribedTransaction
from parsers import PARSERS
from store import load_description_inputs

_BOOKING_CODE_RE = re.compile(r"\s{3,}[A-Z0-9]{2}$")
_REFERENCE_RE = re.compile(r"\*\s?([A-Za-z0-9]{1,6})$")
_NOT_KEY_RE = re.compile(r"[^A-Z0-9]")


def counterparty_key(counterparty: str) -> str:
    """Return a key under which one counterparty's charges group together.

    Removes what changes per charge: an airline booking code after a run of
    spaces (``SKYHOP     V5``), and a short reference after ``*`` that holds
    a digit or is one character (``Streamly*QX7Z41``, ``SHOPMART Mktp UK*R``). A
    reference of letters only is kept, since ``SumUp  *Corner`` names a shop.
    Then everything but letters and digits goes, upper-cased.

    Args:
        counterparty: The name as printed.

    Returns:
        The key, possibly empty.
    """
    name = _BOOKING_CODE_RE.sub("", counterparty.strip())
    match = _REFERENCE_RE.search(name)
    if match and (
        len(match.group(1)) == 1 or any(ch.isdigit() for ch in match.group(1))
    ):
        name = name[: match.start()]
    return _NOT_KEY_RE.sub("", name.upper())


def describe_account(
    conn: sqlite3.Connection, account_id: int
) -> list[DescribedTransaction]:
    """Describe every transaction of an account, oldest first.

    Rows read by a parser without ``describe`` keep their description as the
    counterparty and the ``other`` channel, so nothing silently disappears.

    Args:
        conn: Open ledger connection.
        account_id: Account to describe.

    Returns:
        One described transaction per stored row.
    """
    described: list[DescribedTransaction] = []
    for row in load_description_inputs(conn, account_id):
        parser = PARSERS.get(row["parser"])
        reader = getattr(parser, "describe", None)
        if reader is None:
            bank = BankDescription("other", row["description"])
        else:
            bank = reader(
                row["description"], json.loads(row["raw_json"]), row["amount_minor"]
            )
        described.append(
            DescribedTransaction(
                transaction_id=row["id"],
                posted_on=date.fromisoformat(row["posted_on"]),
                amount_minor=row["amount_minor"],
                channel=bank.channel,
                counterparty=bank.counterparty,
                counterparty_key=counterparty_key(bank.counterparty),
                foreign_amount_minor=bank.foreign_amount_minor,
                foreign_currency=bank.foreign_currency,
            )
        )
    return described
