"""Synthetic statement builders. Every merchant and figure here is invented."""

from __future__ import annotations

import itertools
from datetime import date

from describe import counterparty_key
from models import DescribedTransaction, ParsedStatement, StatementRow


def row(
    day: str,
    amount_minor: int,
    description: str = "CARD PAYMENT EXAMPLE CAFE",
    *,
    balance: int | None = None,
    currency: str = "EUR",
) -> StatementRow:
    """Build one statement row."""
    return StatementRow(
        posted_on=date.fromisoformat(day),
        amount_minor=amount_minor,
        currency=currency,
        description=description,
        balance_after_minor=balance,
        raw={"date": day, "description": description, "amount": str(amount_minor)},
    )


def statement(
    *rows: StatementRow,
    parser: str = "test-csv",
    parser_version: int = 1,
    currency: str = "EUR",
    opening: int | None = None,
    closing: int | None = None,
    period: tuple[str, str] | None = None,
) -> ParsedStatement:
    """Build a parsed statement from rows."""
    return ParsedStatement(
        parser=parser,
        parser_version=parser_version,
        currency=currency,
        rows=tuple(rows),
        period_start=date.fromisoformat(period[0]) if period else None,
        period_end=date.fromisoformat(period[1]) if period else None,
        opening_balance_minor=opening,
        closing_balance_minor=closing,
    )


_TRANSACTION_IDS = itertools.count(1)


def described(
    day: str | date,
    amount_minor: int,
    counterparty: str,
    *,
    channel: str = "card",
    foreign: tuple[int, str] | None = None,
) -> DescribedTransaction:
    """Build one described transaction with a unique id."""
    return DescribedTransaction(
        transaction_id=next(_TRANSACTION_IDS),
        posted_on=date.fromisoformat(day) if isinstance(day, str) else day,
        amount_minor=amount_minor,
        channel=channel,
        counterparty=counterparty,
        counterparty_key=counterparty_key(counterparty),
        foreign_amount_minor=foreign[0] if foreign else None,
        foreign_currency=foreign[1] if foreign else None,
    )
