"""Bank export parsers, one module per format.

A parser module exposes ``NAME``, ``VERSION``, ``matches(content)`` and
``parse(content)``. It reads bytes into a ``models.ParsedStatement`` and never
touches the database; whether the statement may land is ``ingest``'s decision.

Public API:
    PARSERS -- every parser module, by name
    detect  -- the parser whose format a file is in

Example:
    from parsers import detect

    parser = detect(content)
    statement = parser.parse(content)
"""

from __future__ import annotations

from types import ModuleType

from parsers import aib_csv
from parsers.common import StatementFormatError

PARSERS: dict[str, ModuleType] = {aib_csv.NAME: aib_csv}


def detect(content: bytes) -> ModuleType:
    """Return the parser whose format *content* is in.

    Detection is by content, never by filename, since a renamed file is still
    the same format.

    Raises:
        StatementFormatError: If no parser, or more than one, claims the file.
    """
    matches = [parser for parser in PARSERS.values() if parser.matches(content)]
    if not matches:
        supported = ", ".join(sorted(PARSERS))
        raise StatementFormatError(
            f"No parser recognises this file. Supported formats: {supported}. "
            f"For AIB, use Historical Transactions, then Export."
        )
    if len(matches) > 1:
        names = ", ".join(parser.NAME for parser in matches)
        raise StatementFormatError(
            f"Several parsers claim this file ({names}); this is a bug."
        )
    return matches[0]
