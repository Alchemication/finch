"""Amount parsing and formatting."""

from __future__ import annotations

import pytest

from money import format_minor, parse_amount


class TestParseAmount:
    @pytest.mark.parametrize(
        ("text", "expected"),
        [
            ("1,234.56", 123456),
            ("-12.30", -1230),
            ("0.5", 50),
            (" 7 ", 700),
            ("1000000", 100000000),
            ("-0.01", -1),
            ("1,000,000.00", 100000000),
        ],
    )
    def test_accepts_unambiguous_amounts(self, text: str, expected: int) -> None:
        assert parse_amount(text) == expected

    @pytest.mark.parametrize(
        "text",
        [
            "",
            "abc",
            "1.234,56",
            "12.345",
            "1,23.00",
            "12,34",
            "€5.00",
            "--1",
            "1 000.00",
            "+5",
        ],
    )
    def test_rejects_anything_ambiguous(self, text: str) -> None:
        with pytest.raises(ValueError):
            parse_amount(text)

    def test_zero_decimal_currency(self) -> None:
        assert parse_amount("1,500", decimals=0) == 1500

    def test_zero_decimal_currency_rejects_fraction(self) -> None:
        with pytest.raises(ValueError):
            parse_amount("1.5", decimals=0)


class TestFormatMinor:
    @pytest.mark.parametrize(
        ("minor", "currency", "expected"),
        [
            (123456, "EUR", "€1,234.56"),
            (-1230, "EUR", "-€12.30"),
            (0, "EUR", "€0.00"),
            (5, "GBP", "£0.05"),
            (123456, "PLN", "1,234.56 PLN"),
        ],
    )
    def test_formats(self, minor: int, currency: str, expected: str) -> None:
        assert format_minor(minor, currency) == expected

    def test_zero_decimal_currency(self) -> None:
        assert format_minor(1500, "JPY", decimals=0) == "1,500 JPY"

    def test_round_trips_with_parse(self) -> None:
        assert format_minor(parse_amount("-1,234.05")) == "-€1,234.05"
