"""Mask account numbers the first AIB parser kept in raw fields."""

from __future__ import annotations

import json
import re
import sqlite3

NAME = "mask account numbers in raw fields"

_ACCOUNT_NUMBER_RE = re.compile(r"\b\d{6}\s?-\s?(\d{8})\b")


def upgrade(conn: sqlite3.Connection) -> None:
    """Cut sort codes and account numbers in ``raw_json`` to their last four digits.

    AIB's quarterly fee rows print the full sort code and account number in
    Description2, and version 1 of the AIB parser stored that field verbatim,
    against the rule that at most four digits are kept. Rows are evidence and
    otherwise never edited; this is the one correction the rule itself
    requires. Identity keys never included Description2, so no row's identity
    changes. The pattern is copied here rather than imported so this migration
    keeps doing exactly this if parser code changes later.
    """
    rows = conn.execute("SELECT id, raw_json FROM transactions").fetchall()
    for transaction_id, raw_json in rows:
        raw = json.loads(raw_json)
        masked = {
            name: _ACCOUNT_NUMBER_RE.sub(lambda m: f"****{m.group(1)[-4:]}", value)
            if isinstance(value, str)
            else value
            for name, value in raw.items()
        }
        if masked != raw:
            conn.execute(
                "UPDATE transactions SET raw_json = ? WHERE id = ?",
                (
                    json.dumps(masked, sort_keys=True, ensure_ascii=False),
                    transaction_id,
                ),
            )
