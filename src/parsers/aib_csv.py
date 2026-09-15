"""AIB current account CSV, from Historical Transactions, then Export.

Written against a real export downloaded on 2026-09-13. What it showed:

- Twelve columns. Several header names carry a leading space; names are
  compared with surrounding spaces removed.
- One row per posted transaction, oldest first, with the balance after every
  row. Pending card payments are not exported.
- ``DD/MM/YYYY`` posting dates. A card payment's purchase date is not in the
  file.
- Exactly one of Debit Amount and Credit Amount, unsigned, with comma
  thousands separators. Balance is signed-capable and has no separators.
- Description1 is cut to 18 characters. Description2 and Description3 carry
  per-row detail: a direct-debit reference that changes every collection, a
  foreign amount and rate, a cash machine's town and time, or a transfer date.
- Local Currency Amount equals the posted amount and Local Currency equals the
  posted currency on every row, including card payments made in USD or GBP.
- Posted Account is ``sort code - account number``.

Anything that affects a figure and falls outside that is an error naming the
row, so a layout change is noticed rather than absorbed. A new Transaction Type
is kept verbatim, since the amount columns alone decide direction.

Public API:
    NAME, VERSION -- parser identity recorded on every import
    matches       -- whether bytes look like this format
    parse         -- read bytes into a ParsedStatement
    describe      -- channel, counterparty and foreign price from AIB's text

Example:
    from parsers import aib_csv

    statement = aib_csv.parse(path.read_bytes())
"""

from __future__ import annotations

import csv
import io
import re
from datetime import date

from models import BankDescription, ParsedStatement, StatementRow
from money import parse_amount
from parsers.common import StatementFormatError, mask_account_numbers

NAME = "aib-csv"
VERSION = 1

HEADER: tuple[str, ...] = (
    "Posted Account",
    "Posted Transactions Date",
    "Description1",
    "Description2",
    "Description3",
    "Debit Amount",
    "Credit Amount",
    "Balance",
    "Posted Currency",
    "Transaction Type",
    "Local Currency Amount",
    "Local Currency",
)

_ACCOUNT_RE = re.compile(r"^\d{6} - (\d{8})$")
_DATE_RE = re.compile(r"^(\d{2})/(\d{2})/(\d{4})$")
_CURRENCY_RE = re.compile(r"^[A-Z]{3}$")


def _decode(content: bytes) -> str:
    """Decode as UTF-8, with or without a byte-order mark.

    Raises:
        StatementFormatError: If the bytes are not UTF-8. Every export seen so
            far was plain ASCII, so another encoding is a case to inspect
            rather than to guess, since a wrong guess changes descriptions and
            with them row identity.
    """
    try:
        return content.decode("utf-8-sig")
    except UnicodeDecodeError as exc:
        raise StatementFormatError(
            f"The file is not UTF-8 (byte {exc.start} is invalid). The AIB parser "
            f"has only seen plain-text exports; keep the file so its encoding "
            f"can be handled deliberately."
        ) from None


def _header(line: str) -> tuple[str, ...]:
    return tuple(name.strip() for name in next(csv.reader([line]), []))


def matches(content: bytes) -> bool:
    """Return True when *content* starts with the AIB export header."""
    try:
        text = content.decode("utf-8-sig")
    except UnicodeDecodeError:
        return False
    return _header(text.split("\n", 1)[0].rstrip("\r")) == HEADER


def _date(text: str, where: str) -> date:
    match = _DATE_RE.fullmatch(text.strip())
    try:
        if match is None:
            raise ValueError
        day, month, year = (int(part) for part in match.groups())
        return date(year, month, day)
    except ValueError:
        raise StatementFormatError(
            f"{where}: Posted Transactions Date {text!r} is not a DD/MM/YYYY date."
        ) from None


def _amount(text: str, where: str, column: str) -> int:
    try:
        return parse_amount(text)
    except ValueError:
        raise StatementFormatError(f"{where}: {column} is not an amount.") from None


def _unsigned(text: str, where: str, column: str) -> int:
    value = _amount(text, where, column)
    if value < 0:
        raise StatementFormatError(
            f"{where}: {column} is negative; AIB exports amounts unsigned and "
            f"puts direction in the column."
        )
    return value


def parse(content: bytes) -> ParsedStatement:
    """Read an AIB transaction export.

    The account number is reduced to its last four digits before anything is
    kept: it becomes ``account_hint`` and replaces Posted Account in each row's
    raw fields. Every other column is kept verbatim.

    Args:
        content: The CSV file's bytes.

    Returns:
        The statement, with one row per exported transaction.

    Raises:
        StatementFormatError: If the file departs from the observed layout.
    """
    reader = csv.reader(io.StringIO(_decode(content), newline=""))
    header = next(reader, None)
    if header is None or tuple(name.strip() for name in header) != HEADER:
        raise StatementFormatError(
            "Not an AIB transaction export: the header does not match "
            f"{', '.join(HEADER)}. Export again from Historical Transactions."
        )

    rows: list[StatementRow] = []
    account_digits: str | None = None
    currency: str | None = None
    for number, fields in enumerate(reader, start=1):
        where = f"Row {number}"
        if len(fields) != len(HEADER):
            raise StatementFormatError(
                f"{where} has {len(fields)} fields; the header has {len(HEADER)}."
            )
        record = dict(zip(HEADER, fields, strict=True))

        account = _ACCOUNT_RE.fullmatch(record["Posted Account"].strip())
        if account is None:
            raise StatementFormatError(
                f"{where}: Posted Account is not in 'sort code - account number' form."
            )
        if account_digits is None:
            account_digits = account.group(1)
        elif account.group(1) != account_digits:
            raise StatementFormatError(
                f"{where} belongs to a different account from row 1. Export one "
                f"account per file."
            )

        posted_on = _date(record["Posted Transactions Date"], where)
        where = f"{where} ({posted_on})"
        debit = record["Debit Amount"].strip()
        credit = record["Credit Amount"].strip()
        if bool(debit) == bool(credit):
            raise StatementFormatError(
                f"{where} must have exactly one of Debit Amount and Credit Amount."
            )
        amount = (
            -_unsigned(debit, where, "Debit Amount")
            if debit
            else _unsigned(credit, where, "Credit Amount")
        )

        row_currency = record["Posted Currency"].strip()
        if not _CURRENCY_RE.fullmatch(row_currency):
            raise StatementFormatError(f"{where}: Posted Currency is not an ISO code.")
        if currency is None:
            currency = row_currency
        elif row_currency != currency:
            raise StatementFormatError(
                f"{where} is posted in {row_currency}, but row 1 is in {currency}."
            )

        local = _unsigned(
            record["Local Currency Amount"], where, "Local Currency Amount"
        )
        if record["Local Currency"].strip() != row_currency or local != abs(amount):
            raise StatementFormatError(
                f"{where}: the local currency amount differs from the posted amount. "
                f"No export seen so far did this; keep the file so the case can be "
                f"handled deliberately."
            )

        raw = {name: mask_account_numbers(value) for name, value in record.items()}
        raw["Posted Account"] = f"****{account_digits[-4:]}"
        rows.append(
            StatementRow(
                posted_on=posted_on,
                amount_minor=amount,
                currency=row_currency,
                description=mask_account_numbers(record["Description1"]),
                balance_after_minor=_amount(record["Balance"], where, "Balance"),
                bank_reference=record["Transaction Type"].strip() or None,
                raw=raw,
            )
        )

    if not rows or account_digits is None or currency is None:
        raise StatementFormatError(
            "The export has a header but no transactions. Choose a date range that has some."
        )
    return ParsedStatement(
        parser=NAME,
        parser_version=VERSION,
        currency=currency,
        rows=tuple(rows),
        account_hint=account_digits[-4:],
    )


_PREFIXES: tuple[tuple[str, str], ...] = (
    ("VDP-", "card"),
    ("VDC-", "card"),
    ("VDA-", "atm"),
    ("D/D ", "direct_debit"),
    ("*INET ", "transfer_out"),
    ("*MOBI ", "transfer_out"),
)
"""Description1 prefixes and the channel each names, as seen in real exports."""

_SEPA_REFERENCE_RE = re.compile(r"^IE\d{14}$")
_FEE_RE = re.compile(r"^(FEE-QTR|ACCOUNT FEE|STAMP DUTY|PYMT FEE)\b")
_FOREIGN_RE = re.compile(r"^(\d+\.\d{2}) ([A-Z]{3})@$")


def describe(
    description: str, raw: dict[str, str], amount_minor: int
) -> BankDescription:
    """Read channel, counterparty and foreign price from AIB's text.

    Rules, from a real export:

    - ``VDP-`` and ``VDC-`` are card payments, ``VDA-`` cash withdrawals,
      ``D/D`` direct debits, ``*INET`` and ``*MOBI`` transfers sent.
    - A Description1 that is only a SEPA reference (``IE`` and 14 digits)
      carries the payment's own text in Description2 instead.
    - Quarterly and monthly account fees, stamp duty and payment fees are fees.
    - Any other credit is a transfer received, such as salary.
    - Description2 of ``12.50 USD@`` gives the price in the currency charged.

    Args:
        description: The stored description (Description1).
        raw: The row's raw fields.
        amount_minor: Signed amount.

    Returns:
        What the text says.
    """
    first = description.strip()
    second = raw.get("Description2", "").strip()
    foreign = _FOREIGN_RE.fullmatch(second)
    foreign_amount = parse_amount(foreign.group(1)) if foreign else None
    foreign_currency = foreign.group(2) if foreign else None
    if _SEPA_REFERENCE_RE.fullmatch(first) and second:
        first = second

    fee = _FEE_RE.match(first)
    if fee:
        return BankDescription("fee", fee.group(1), foreign_amount, foreign_currency)
    for prefix, channel in _PREFIXES:
        if first.startswith(prefix):
            counterparty = first[len(prefix) :].strip() or first
            return BankDescription(
                channel, counterparty, foreign_amount, foreign_currency
            )
    channel = "transfer_in" if amount_minor > 0 else "other"
    return BankDescription(channel, first, foreign_amount, foreign_currency)
