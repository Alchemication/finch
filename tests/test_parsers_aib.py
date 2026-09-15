"""The AIB CSV parser, against a synthetic export shaped like a real one."""

from __future__ import annotations

import csv
import io
from pathlib import Path

import pytest

from ingest import check_statement
from parsers import aib_csv, detect
from parsers.common import StatementFormatError

FIXTURE = Path(__file__).parent / "fixtures" / "aib" / "export.csv"


def _content() -> bytes:
    return FIXTURE.read_bytes()


def _variant(row_index: int, changes: dict[str, str]) -> bytes:
    """Return the fixture with some columns of one data row replaced."""
    lines = FIXTURE.read_text().split("\n")
    fields = next(csv.reader([lines[row_index + 1]]))
    for column, value in changes.items():
        fields[aib_csv.HEADER.index(column)] = value
    out = io.StringIO()
    csv.writer(out, lineterminator="").writerow(fields)
    lines[row_index + 1] = out.getvalue()
    return "\n".join(lines).encode()


class TestDetect:
    def test_recognises_an_aib_export(self) -> None:
        assert detect(_content()) is aib_csv

    def test_unknown_file_names_supported_formats(self) -> None:
        with pytest.raises(StatementFormatError, match="aib-csv"):
            detect(b"Date,Amount\n2026-08-01,1.00")


class TestParse:
    def test_reads_every_row(self) -> None:
        statement = aib_csv.parse(_content())
        assert len(statement.rows) == 10
        assert (statement.parser, statement.parser_version) == ("aib-csv", 1)
        assert statement.currency == "EUR"
        assert statement.account_hint == "1234"

    def test_debits_are_negative_and_credits_positive(self) -> None:
        rows = aib_csv.parse(_content()).rows
        assert rows[0].amount_minor == -1299
        assert rows[7].amount_minor == 320

    def test_thousands_separators(self) -> None:
        rows = aib_csv.parse(_content()).rows
        assert rows[6].amount_minor == -115000
        assert rows[8].amount_minor == 425000

    def test_every_row_has_a_balance_and_the_statement_reconciles(self) -> None:
        statement = aib_csv.parse(_content())
        assert all(row.balance_after_minor is not None for row in statement.rows)
        assert statement.rows[-1].balance_after_minor == 541272
        assert check_statement(statement) == []

    def test_description_is_description1_and_detail_stays_raw(self) -> None:
        direct_debit = aib_csv.parse(_content()).rows[3]
        assert direct_debit.description == "D/D EXAMPLE INSURA"
        assert direct_debit.bank_reference == "Direct Debit"
        assert direct_debit.raw["Description2"] == "IE26080400000001"

    def test_foreign_currency_detail_is_kept(self) -> None:
        card = aib_csv.parse(_content()).rows[4]
        assert (card.raw["Description2"], card.raw["Description3"]) == (
            "20.00 USD@",
            "1.150000",
        )

    def test_account_number_is_never_kept(self) -> None:
        statement = aib_csv.parse(_content())
        assert "55501234" not in repr(statement)
        assert "987650" not in repr(statement)
        assert statement.rows[0].raw["Posted Account"] == "****1234"

    def test_byte_order_mark_is_accepted(self) -> None:
        content = b"\xef\xbb\xbf" + _content()
        assert aib_csv.matches(content)
        assert len(aib_csv.parse(content).rows) == 10

    def test_new_transaction_type_is_kept_verbatim(self) -> None:
        row = aib_csv.parse(_variant(0, {"Transaction Type": "Standing Order"})).rows[0]
        assert row.bank_reference == "Standing Order"


class TestRejects:
    def test_changed_header(self) -> None:
        content = _content().replace(b"Debit Amount", b"Debit", 1)
        assert not aib_csv.matches(content)
        with pytest.raises(StatementFormatError, match="header"):
            aib_csv.parse(content)

    def test_non_utf8(self) -> None:
        content = _content().replace(b"CORNER CAFE", b"CORNER CAF\xc9", 1)
        with pytest.raises(StatementFormatError, match="not UTF-8"):
            aib_csv.parse(content)

    def test_wrong_field_count(self) -> None:
        lines = FIXTURE.read_text().split("\n")
        lines[1] += ',"extra"'
        with pytest.raises(StatementFormatError, match="Row 1 has 13 fields"):
            aib_csv.parse("\n".join(lines).encode())

    def test_both_amounts_without_leaking_the_description(self) -> None:
        with pytest.raises(StatementFormatError, match="exactly one") as caught:
            aib_csv.parse(_variant(0, {"Credit Amount": "1.00"}))
        assert "EXAMPLE" not in str(caught.value)

    def test_neither_amount(self) -> None:
        with pytest.raises(StatementFormatError, match="exactly one"):
            aib_csv.parse(_variant(0, {"Debit Amount": ""}))

    def test_signed_amount(self) -> None:
        with pytest.raises(StatementFormatError, match="negative"):
            aib_csv.parse(_variant(0, {"Debit Amount": "-12.99"}))

    def test_iso_date(self) -> None:
        with pytest.raises(StatementFormatError, match="DD/MM/YYYY"):
            aib_csv.parse(_variant(0, {"Posted Transactions Date": "2026-08-03"}))

    def test_impossible_date(self) -> None:
        with pytest.raises(StatementFormatError, match="DD/MM/YYYY"):
            aib_csv.parse(_variant(0, {"Posted Transactions Date": "31/02/2026"}))

    def test_second_account_without_leaking_its_number(self) -> None:
        with pytest.raises(StatementFormatError, match="different account") as caught:
            aib_csv.parse(_variant(1, {"Posted Account": "987650 - 99990000"}))
        assert "9999" not in str(caught.value)

    def test_second_currency(self) -> None:
        changes = {"Posted Currency": "GBP", "Local Currency": "GBP"}
        with pytest.raises(StatementFormatError, match="posted in GBP"):
            aib_csv.parse(_variant(1, changes))

    def test_local_amount_differing_from_posted(self) -> None:
        with pytest.raises(StatementFormatError, match="local currency amount"):
            aib_csv.parse(_variant(4, {"Local Currency Amount": " 20.00"}))

    def test_header_only(self) -> None:
        header = FIXTURE.read_text().split("\n")[0]
        with pytest.raises(StatementFormatError, match="no transactions"):
            aib_csv.parse(header.encode())


class TestAccountNumberMasking:
    def test_account_number_anywhere_in_a_row_is_masked(self) -> None:
        row = aib_csv.parse(_variant(9, {"Description2": "987650-55501234"})).rows[9]
        assert row.raw["Description2"] == "****1234"


class TestDescribe:
    @pytest.mark.parametrize(
        ("first", "second", "amount", "channel", "counterparty"),
        [
            ("VDP-APPSTORE/BILL", "", -799, "card", "APPSTORE/BILL"),
            ("VDC-CORNER CAFE", "", -450, "card", "CORNER CAFE"),
            ("VDA-EXAMPLE TOWN", "CORK", -10000, "atm", "EXAMPLE TOWN"),
            (
                "D/D EXAMPLE INSURA",
                "IE26080400000001",
                -4510,
                "direct_debit",
                "EXAMPLE INSURA",
            ),
            ("*INET EXAMPLE-JUL26", "", -45000, "transfer_out", "EXAMPLE-JUL26"),
            ("*MOBI EXAMPLE", "", -45000, "transfer_out", "EXAMPLE"),
            (
                "IE26011300000001",
                "*INET EXAMPLE BUILD",
                -185000,
                "transfer_out",
                "EXAMPLE BUILD",
            ),
            ("IE26011300000001", "PYMT FEE O07", -1200, "fee", "PYMT FEE"),
            (
                "IE26031200000002",
                "EXAMPLE INSURANCE",
                95000,
                "transfer_in",
                "EXAMPLE INSURANCE",
            ),
            (
                "12345678-26-000001",
                "IE26082700000003",
                425000,
                "transfer_in",
                "12345678-26-000001",
            ),
            ("FEE-QTR TO 28FEB26", "****1234", -2800, "fee", "FEE-QTR"),
            ("ACCOUNT FEE AUG 26", "", -600, "fee", "ACCOUNT FEE"),
            ("STAMP DUTY 1234", "", -350, "fee", "STAMP DUTY"),
            ("VDP-Example.ie", "", 320, "card", "Example.ie"),
            ("UNEXPECTED DEBIT", "", -100, "other", "UNEXPECTED DEBIT"),
        ],
    )
    def test_channel_and_counterparty(
        self, first: str, second: str, amount: int, channel: str, counterparty: str
    ) -> None:
        description = aib_csv.describe(first, {"Description2": second}, amount)
        assert (description.channel, description.counterparty) == (
            channel,
            counterparty,
        )

    def test_foreign_price(self) -> None:
        description = aib_csv.describe(
            "VDP-EXAMPLE AI",
            {"Description2": "20.00 USD@", "Description3": "1.150000"},
            -1739,
        )
        assert (description.foreign_amount_minor, description.foreign_currency) == (
            2000,
            "USD",
        )
