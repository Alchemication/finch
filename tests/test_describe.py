"""Counterparty keys and describing stored transactions."""

from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest

from describe import counterparty_key, describe_account
from ingest import import_statement
from models import Account
from parsers import aib_csv
from tests.factories import row, statement

FIXTURE = Path(__file__).parent / "fixtures" / "aib" / "export.csv"


class TestCounterpartyKey:
    @pytest.mark.parametrize(
        ("name", "key"),
        [
            ("Streamly*QX7Z41", "STREAMLY"),
            ("Streamly UK", "STREAMLYUK"),
            ("SHOPMART Mktp UK*R", "SHOPMARTMKTPUK"),
            ("WWW.SHOPMART.* R", "WWWSHOPMART"),
            ("SKYHOP     V5", "SKYHOP"),
            ("SumUp  *Corner", "SUMUPCORNER"),
            ("CHATCO *ASSIST", "CHATCOASSIST"),
            ("RIDENOW* KQ2P8", "RIDENOW"),
            ("Walletly**5521*", "WALLETLY5521"),
            ("EXAMPLE *VIDEOS", "EXAMPLEVIDEOS"),
        ],
    )
    def test_keys(self, name: str, key: str) -> None:
        assert counterparty_key(name) == key


class TestDescribeAccount:
    def test_aib_rows_use_the_aib_describer(
        self, conn: sqlite3.Connection, account: Account, tmp_path: Path
    ) -> None:
        content = FIXTURE.read_bytes()
        import_statement(
            conn,
            account=account,
            statement=aib_csv.parse(content),
            content=content,
            source_name="export.csv",
            archive_root=tmp_path,
        )
        rows = describe_account(conn, account.id)
        assert [r.channel for r in rows] == [
            "card",
            "card",
            "card",
            "direct_debit",
            "card",
            "atm",
            "direct_debit",
            "card",
            "transfer_in",
            "fee",
        ]
        assert (rows[4].foreign_amount_minor, rows[4].foreign_currency) == (2000, "USD")

    def test_rows_from_a_parser_without_a_describer_stay_visible(
        self, conn: sqlite3.Connection, account: Account, tmp_path: Path
    ) -> None:
        import_statement(
            conn,
            account=account,
            statement=statement(row("2026-09-01", -100, "SOMETHING")),
            content=b"x",
            source_name="x.csv",
            archive_root=tmp_path,
        )
        [described] = describe_account(conn, account.id)
        assert (described.channel, described.counterparty) == ("other", "SOMETHING")
