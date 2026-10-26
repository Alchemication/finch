"""Plain dataclasses for the ledger, validated on construction. No persistence.

Public API:
    Account          -- one bank account a profile holds
    StatementRow     -- one transaction exactly as a statement reported it
    ParsedStatement  -- what a parser hands to the import pipeline
    Document         -- a contract, letter or agreement kept in the archive
    ACCOUNT_KINDS    -- account kinds the schema accepts

Example:
    from models import Account

    account = Account(
        name="aib-current", institution="AIB", kind="current", currency="EUR"
    )
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import date

ACCOUNT_KINDS: tuple[str, ...] = ("current", "savings", "credit_card", "loan")
"""Kept in step with the CHECK constraint on ``accounts.kind``."""

_ACCOUNT_NAME_RE = re.compile(r"^[a-z0-9][a-z0-9_-]*$")
_CURRENCY_RE = re.compile(r"^[A-Z]{3}$")
_HINT_RE = re.compile(r"^\d{4}$")


@dataclass(frozen=True)
class Account:
    """One bank account.

    Attributes:
        name: Short handle used on the command line, e.g. ``aib-current``.
        institution: The bank, as a person would name it.
        kind: One of ``ACCOUNT_KINDS``.
        currency: ISO 4217 code the account is denominated in.
        identifier_hint: Last four digits of the account number, to tell two
            accounts at one bank apart. Never the full number or IBAN.
        id: Database id; None until stored.
    """

    name: str
    institution: str
    kind: str
    currency: str
    identifier_hint: str | None = None
    id: int | None = None

    def __post_init__(self) -> None:
        if not _ACCOUNT_NAME_RE.fullmatch(self.name):
            raise ValueError(
                f"Invalid account name {self.name!r}; use lowercase letters, "
                f"digits, '_' or '-'."
            )
        if not self.institution.strip():
            raise ValueError("Account institution cannot be empty.")
        if self.kind not in ACCOUNT_KINDS:
            raise ValueError(
                f"Unknown account kind {self.kind!r}; expected one of "
                f"{', '.join(ACCOUNT_KINDS)}."
            )
        if not _CURRENCY_RE.fullmatch(self.currency):
            raise ValueError(
                f"Currency must be a three-letter ISO code such as EUR, "
                f"not {self.currency!r}."
            )
        if self.identifier_hint is not None and not _HINT_RE.fullmatch(
            self.identifier_hint
        ):
            raise ValueError(
                "The identifier hint is the last four digits of the account "
                "number and nothing more."
            )


@dataclass(frozen=True)
class Document:
    """A file kept for reference that is not a statement.

    Attributes:
        sha256: Hash of the file's bytes; names its directory in the archive.
        original_name: Filename it was added from, for recognition only.
        title: What a person would call it, e.g. "Car finance agreement".
        dated_on: The date the document carries, if known.
        note: Anything worth remembering about it.
        id: Database id; None until stored.
    """

    sha256: str
    original_name: str
    title: str
    dated_on: date | None = None
    note: str | None = None
    id: int | None = None

    def __post_init__(self) -> None:
        if not self.title.strip():
            raise ValueError("A document needs a title; pass --title.")


@dataclass(frozen=True)
class StatementRow:
    """One transaction exactly as a statement reported it.

    Attributes:
        posted_on: Date the bank posted it.
        amount_minor: Signed amount in minor units. Negative is money leaving
            the account.
        currency: Currency of ``amount_minor``.
        description: The bank's description, verbatim apart from joining
            multi-part fields with a single space.
        balance_after_minor: Balance the statement printed after this row, or
            None where it printed none.
        bank_reference: The bank's own transaction type or reference, verbatim.
        raw: Every source field of the row as text, untouched, so a later
            parser version can reinterpret it without the original file.
    """

    posted_on: date
    amount_minor: int
    currency: str
    description: str
    balance_after_minor: int | None = None
    bank_reference: str | None = None
    raw: dict[str, str] = field(default_factory=dict)


@dataclass(frozen=True)
class ParsedStatement:
    """What a parser hands to the import pipeline.

    Parsers read a format and never write. Rows must be oldest first, in the
    order the bank applied them, because that order is what the running
    balance check walks.

    Attributes:
        parser: Stable parser name, e.g. ``aib-csv``.
        parser_version: Bumped whenever the parser's output for the same file
            could change. Row identity depends on it.
        currency: Currency of every row.
        rows: Transactions, oldest first.
        period_start: First day the statement claims to cover, when it says.
        period_end: Last day the statement claims to cover, when it says.
        opening_balance_minor: Printed opening balance, when there is one.
        closing_balance_minor: Printed closing balance, when there is one.
        account_hint: Last four digits of the account the file says it belongs
            to, when it says. Checked against the account being imported into.
    """

    parser: str
    parser_version: int
    currency: str
    rows: tuple[StatementRow, ...]
    period_start: date | None = None
    period_end: date | None = None
    opening_balance_minor: int | None = None
    closing_balance_minor: int | None = None
    account_hint: str | None = None


CHANNELS: tuple[str, ...] = (
    "card",
    "atm",
    "direct_debit",
    "transfer_out",
    "transfer_in",
    "fee",
    "other",
)
"""How money moved, as far as the bank's text says."""


@dataclass(frozen=True)
class BankDescription:
    """What a bank's own text says about one transaction.

    Attributes:
        channel: One of ``CHANNELS``.
        counterparty: The other party's name as printed, prefix removed. For a
            transfer this is often a reference typed per payment.
        foreign_amount_minor: The price in the currency charged, when the bank
            reports a conversion.
        foreign_currency: That currency's ISO code.
    """

    channel: str
    counterparty: str
    foreign_amount_minor: int | None = None
    foreign_currency: str | None = None

    def __post_init__(self) -> None:
        if self.channel not in CHANNELS:
            raise ValueError(f"Unknown channel {self.channel!r}.")


@dataclass(frozen=True)
class DescribedTransaction:
    """A stored transaction with what its bank text says. Derived, never stored.

    Attributes:
        transaction_id: The ledger row.
        posted_on: Posting date.
        amount_minor: Signed amount in the account's currency.
        channel: One of ``CHANNELS``.
        counterparty: Name or reference as printed.
        counterparty_key: Grouping key, see ``describe.counterparty_key``.
        foreign_amount_minor: Price in the currency charged, when known.
        foreign_currency: That currency, when known.
    """

    transaction_id: int
    posted_on: date
    amount_minor: int
    channel: str
    counterparty: str
    counterparty_key: str
    foreign_amount_minor: int | None = None
    foreign_currency: str | None = None
