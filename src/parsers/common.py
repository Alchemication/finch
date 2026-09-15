"""What every parser shares.

Public API:
    StatementFormatError -- a file is not exactly in the format a parser reads
    mask_account_numbers -- cut sort codes and account numbers to four digits
"""

from __future__ import annotations

import re


class StatementFormatError(ValueError):
    """A file is not exactly in the format a parser was written against.

    Messages name a row and a column, never a description or an account
    number, and say what to do about it.
    """


_ACCOUNT_NUMBER_RE = re.compile(r"\b\d{6}\s?-\s?(\d{8})\b")
"""An Irish sort code and account number, with or without spaces round the dash."""


def mask_account_numbers(text: str) -> str:
    """Replace every sort code and account number in *text* with its last four digits.

    AIB prints the full number in more places than Posted Account: quarterly
    fee rows carry it in Description2. Masking every field is what keeps the
    rule that at most four digits are stored.
    """
    return _ACCOUNT_NUMBER_RE.sub(lambda match: f"****{match.group(1)[-4:]}", text)
