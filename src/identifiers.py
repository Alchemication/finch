"""The owner's own account identifiers: IBAN validation and its parts.

Bank rows never carry more than the last four digits of an account number.
The owner's own IBAN and BIC are typed in by hand, so they can be looked up
later; this module checks them so a typo is caught on entry, and derives the
sort code and account number an Irish or UK IBAN contains.

Nothing here logs or echoes an identifier: error messages describe what is
wrong without repeating the value.

Public API:
    AccountIdentifiers -- a validated IBAN and optional BIC
    normalise_iban     -- upper case, no spaces
    domestic_parts     -- sort code and account number inside an IE or GB IBAN

Example:
    from identifiers import AccountIdentifiers

    ids = AccountIdentifiers(iban="IE29 AIBK 9311 5212 3456 78", bic="AIBKIE2D")
"""

from __future__ import annotations

import re
from dataclasses import dataclass

_IBAN_LENGTHS: dict[str, int] = {"IE": 22, "GB": 22}
"""Countries whose IBAN layout is known here. Others are checked by checksum
and the general shape only."""

_IBAN_RE = re.compile(r"^[A-Z]{2}\d{2}[A-Z0-9]{11,30}$")
_BIC_RE = re.compile(r"^[A-Z]{4}[A-Z]{2}[A-Z0-9]{2}([A-Z0-9]{3})?$")


def normalise_iban(text: str) -> str:
    """Return *text* upper-cased with spaces removed."""
    return re.sub(r"\s+", "", text).upper()


def _checksum_ok(iban: str) -> bool:
    rearranged = iban[4:] + iban[:4]
    digits = "".join(str(int(char, 36)) for char in rearranged)
    return int(digits) % 97 == 1


def domestic_parts(iban: str) -> tuple[str, str] | None:
    """Return ``(sort code, account number)`` for an Irish or UK IBAN.

    Both countries lay an IBAN out as country, check digits, four-letter bank
    code, six-digit sort code and eight-digit account number.

    Returns:
        The two parts, or None for any other country.
    """
    if iban[:2] not in _IBAN_LENGTHS:
        return None
    return iban[8:14], iban[14:22]


@dataclass(frozen=True)
class AccountIdentifiers:
    """The owner's own identifiers for one account.

    Attributes:
        iban: Normalised IBAN, checksum-verified.
        bic: BIC (SWIFT code), 8 or 11 characters, or None.
    """

    iban: str
    bic: str | None = None

    def __post_init__(self) -> None:
        iban = normalise_iban(self.iban)
        object.__setattr__(self, "iban", iban)
        if not _IBAN_RE.fullmatch(iban):
            raise ValueError(
                "That is not an IBAN: it starts with a country code and two check "
                "digits, e.g. IE29 AIBK ..."
            )
        expected = _IBAN_LENGTHS.get(iban[:2])
        if expected is not None and len(iban) != expected:
            raise ValueError(
                f"A {iban[:2]} IBAN has {expected} characters; this one has "
                f"{len(iban)}. Check it against the bank's app."
            )
        if not _checksum_ok(iban):
            raise ValueError(
                "The IBAN's check digits do not match; a character is probably "
                "mistyped. Copy it from the bank's app."
            )
        if self.bic is not None:
            bic = self.bic.replace(" ", "").upper()
            object.__setattr__(self, "bic", bic)
            if not _BIC_RE.fullmatch(bic):
                raise ValueError("A BIC is 8 or 11 letters and digits, e.g. AIBKIE2D.")

    @property
    def last4(self) -> str:
        """The last four characters, comparable with an account's hint."""
        return self.iban[-4:]

    @property
    def grouped_iban(self) -> str:
        """The IBAN in groups of four, as banks print it."""
        return " ".join(self.iban[i : i + 4] for i in range(0, len(self.iban), 4))
