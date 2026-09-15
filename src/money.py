"""Money as integer minor units, parsed strictly.

A float cannot hold 0.10 exactly, and a ledger checked to the cent against a
bank's running balance cannot afford a representation that drifts on every row.
Amounts are integers in minor units from the moment they are parsed until they
are formatted for a person.

Public API:
    parse_amount -- "1,234.56" to 123456, refusing anything ambiguous
    format_minor -- 123456 to "€1,234.56"

Example:
    from money import format_minor, parse_amount

    format_minor(parse_amount("-12.30"))  # "-€12.30"
"""

from __future__ import annotations

import re

_AMOUNT_RE = re.compile(r"^(-)?(\d{1,3}(?:,\d{3})+|\d+)(?:\.(\d+))?$")
_SYMBOLS: dict[str, str] = {"EUR": "€", "GBP": "£", "USD": "$"}


def parse_amount(text: str, *, decimals: int = 2) -> int:
    """Parse a decimal amount into signed minor units.

    Accepts an optional leading minus, comma thousands separators in whole
    groups of three, and at most ``decimals`` fractional digits. Everything
    else is rejected rather than guessed: ``1.234,56`` is a normal amount in
    much of Europe, and a parser that quietly read it as 1.23 would pass every
    test written in the other convention.

    Args:
        text: The amount as printed.
        decimals: Minor-unit digits for the currency.

    Returns:
        The amount in minor units.

    Raises:
        ValueError: If the text is not an unambiguous amount.
    """
    match = _AMOUNT_RE.fullmatch(text.strip())
    if match is None:
        raise ValueError(f"Not an amount: {text!r}")
    sign, whole, fraction = match.groups()
    fraction = fraction or ""
    if len(fraction) > decimals:
        raise ValueError(f"Amount {text!r} has more than {decimals} decimal places.")
    minor = int(whole.replace(",", "")) * 10**decimals
    minor += int(fraction.ljust(decimals, "0") or "0")
    return -minor if sign else minor


def format_minor(minor: int, currency: str = "EUR", *, decimals: int = 2) -> str:
    """Format signed minor units for a person.

    Args:
        minor: Amount in minor units.
        currency: ISO 4217 code; common ones get a symbol.
        decimals: Minor-unit digits for the currency.

    Returns:
        E.g. ``€1,234.56``, ``-€12.30`` or ``1,234.56 PLN``.
    """
    sign = "-" if minor < 0 else ""
    whole, fraction = divmod(abs(minor), 10**decimals)
    number = f"{whole:,}" + (f".{fraction:0{decimals}d}" if decimals else "")
    symbol = _SYMBOLS.get(currency)
    return f"{sign}{symbol}{number}" if symbol else f"{sign}{number} {currency}"
