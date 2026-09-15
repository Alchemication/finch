"""Recurring-payment detection on synthetic described transactions.

Every merchant, reference, amount and date here is invented. Where a test
reproduces a shape seen in real data, such as a price step or drifting transfer
dates, the shape is kept and the values are not.
"""

from __future__ import annotations

from datetime import date, timedelta

import pytest

from models import DescribedTransaction
from recurring import build_report, detect_series
from tests.factories import described


def _month(start: date, offset: int) -> date:
    index = start.month - 1 + offset
    return date(start.year + index // 12, index % 12 + 1, start.day)


def _monthly(
    counterparty: str,
    amounts: list[int],
    *,
    start: date = date(2025, 2, 10),
    channel: str = "card",
    currency: str | None = None,
    eur: list[int] | None = None,
) -> list[DescribedTransaction]:
    sign = 1 if channel == "transfer_in" else -1
    rows = []
    for offset, amount in enumerate(amounts):
        day = _month(start, offset)
        if currency is None:
            rows.append(described(day, sign * amount, counterparty, channel=channel))
        else:
            assert eur is not None
            rows.append(
                described(
                    day,
                    sign * eur[offset],
                    counterparty,
                    channel=channel,
                    foreign=(amount, currency),
                )
            )
    return rows


def _detect(rows: list[DescribedTransaction], **kwargs: object):
    return detect_series(rows, currency="EUR", **kwargs)


class TestMonthly:
    def test_fixed_monthly_payment(self) -> None:
        [series] = _detect(_monthly("EXAMPLE STREAM", [1299] * 6))
        assert (series.cadence.name, series.fixed, series.status) == (
            "monthly",
            True,
            "active",
        )
        assert (series.current_minor, series.monthly_minor, series.changes) == (
            1299,
            1299,
            (),
        )

    def test_price_change_is_dated_and_confirmed(self) -> None:
        rows = _monthly(
            "EXAMPLE MOBILE", [3500] * 4 + [3650] * 3, channel="direct_debit"
        )
        [series] = _detect(rows)
        [change] = series.changes
        assert (change.on, change.before_minor, change.after_minor) == (
            date(2025, 6, 10),
            3500,
            3650,
        )
        assert change.confirmed

    def test_change_on_the_latest_charge_is_unconfirmed(self) -> None:
        rows = _monthly(
            "EXAMPLE LENDER", [98750] * 5 + [110600], channel="direct_debit"
        )
        [series] = _detect(rows)
        assert not series.changes[0].confirmed

    def test_one_odd_charge_is_not_a_change(self) -> None:
        rows = _monthly(
            "EXAMPLE TV", [1800, 1800, 1950, 1800, 1800], channel="direct_debit"
        )
        [series] = _detect(rows)
        assert series.changes == ()

    def test_skipped_month_keeps_the_series(self) -> None:
        days = [
            date(2025, 2, 10),
            date(2025, 3, 10),
            date(2025, 5, 10),
            date(2025, 6, 10),
        ]
        assert (
            len(_detect([described(day, -1299, "EXAMPLE STREAM") for day in days])) == 1
        )

    def test_several_subscriptions_from_one_merchant(self) -> None:
        rows = _monthly("APPSTORE/BILL", [799] * 6, start=date(2025, 2, 14))
        rows += _monthly("APPSTORE/BILL", [899] * 6, start=date(2025, 2, 9))
        assert sorted(s.current_minor for s in _detect(rows)) == [799, 899]


class TestNotRecurring:
    def test_daily_habit(self) -> None:
        rows = [
            described(date(2025, month, day), -450, "CORNER COFFEE")
            for month in range(2, 8)
            for day in (3, 7, 10, 14, 17, 21, 24, 28)
        ]
        assert _detect(rows) == []

    def test_irregular_visits_at_a_fixed_price(self) -> None:
        day = date(2025, 2, 3)
        days = [day]
        for gap in (63, 29, 55, 50, 41, 77, 112, 25):
            day += timedelta(days=gap)
            days.append(day)
        assert _detect([described(day, -3200, "EXAMPLE BARBER") for day in days]) == []

    def test_weekly_shop_of_varying_amounts(self) -> None:
        start = date(2025, 2, 3)
        rows = [
            described(
                start + timedelta(weeks=week),
                -(12000 + week * 337 % 1800),
                "EXAMPLE GROCER",
            )
            for week in range(26)
        ]
        assert _detect(rows) == []

    def test_cash_withdrawals(self) -> None:
        assert _detect(_monthly("EXAMPLE TOWN", [10000] * 6, channel="atm")) == []

    def test_card_refunds(self) -> None:
        rows = [
            described(_month(date(2025, 2, 10), i), 1299, "EXAMPLE STREAM")
            for i in range(6)
        ]
        assert _detect(rows) == []

    def test_small_purchase_a_year_apart(self) -> None:
        rows = [
            described(date(2025, 3, 1), -450, "EXAMPLE CAFE"),
            described(date(2026, 3, 3), -450, "EXAMPLE CAFE"),
        ]
        assert _detect(rows) == []

    def test_varying_charges_a_year_apart(self) -> None:
        rows = [
            described(date(2025, 5, 12), -4500, "EXAMPLE SHOES"),
            described(date(2026, 5, 20), -5500, "EXAMPLE SHOES"),
        ]
        assert _detect(rows) == []


class TestTransfersAndIncome:
    def test_transfers_group_by_amount_not_reference(self) -> None:
        references = [
            "NURSERY-FEB25",
            "NURSERY",
            "NURSERYFEES",
            "Nursery",
            "nursery-fees",
            "nursery-jul25",
        ]
        rows = [
            described(
                _month(date(2025, 2, 6), i), -45000, reference, channel="transfer_out"
            )
            for i, reference in enumerate(references)
        ]
        rows.append(
            described(date(2025, 4, 16), -800000, "CARDEALER", channel="transfer_out")
        )
        [series] = _detect(rows)
        assert (series.current_minor, series.name, len(series.names)) == (
            45000,
            "nursery-jul25",
            6,
        )

    def test_salary_with_a_raise(self) -> None:
        amounts = [512340, 513960, 512341, 523600, 523600, 523600]
        rows = [
            described(
                _month(date(2025, 2, 26), i),
                amount,
                f"9000000{i}-11-10000{i}",
                channel="transfer_in",
            )
            for i, amount in enumerate(amounts)
        ]
        [series] = _detect(rows)
        assert series.direction == "in"
        [change] = series.changes
        assert (change.before_minor, change.after_minor) == (512340, 523600)

    def test_salary_does_not_drift_into_other_credits(self) -> None:
        rows = [
            described(
                _month(date(2025, 2, 26), i), 512340, f"REF{i}", channel="transfer_in"
            )
            for i in range(5)
        ]
        rows += [
            described(date(2025, 7, 24), 380000, "REFUND", channel="transfer_in"),
            described(date(2025, 9, 5), 225000, "OWN ACCOUNT", channel="transfer_in"),
            described(date(2025, 10, 6), 172500, "OTHER", channel="transfer_in"),
        ]
        [series] = _detect(rows)
        assert {charge.amount_minor for charge in series.charges} == {512340}


class TestForeignPrices:
    def test_exchange_rate_movement_is_not_a_price_change(self) -> None:
        rows = _monthly(
            "Streamly*QX7Z41",
            [1299] * 6,
            currency="USD",
            eur=[1240, 1228, 1201, 1167, 1131, 1115],
        )
        [series] = _detect(rows)
        assert (series.fixed, series.changes) == (True, ())
        assert (
            series.price_currency,
            series.current_price_minor,
            series.current_minor,
        ) == (
            "USD",
            1299,
            1115,
        )

    def test_price_change_in_the_charged_currency(self) -> None:
        rows = _monthly(
            "Streamly UK",
            [699] * 4 + [799] * 3,
            currency="GBP",
            eur=[830] * 4 + [945] * 3,
        )
        [series] = _detect(rows)
        [change] = series.changes
        assert (change.currency, change.before_minor, change.after_minor) == (
            "GBP",
            699,
            799,
        )


class TestNames:
    def test_truncated_names_are_one_payment(self) -> None:
        names = ["Example Videos", "EXAMPLE *VIDEO"] * 3
        rows = [
            described(_month(date(2025, 2, 11), i), -999, n)
            for i, n in enumerate(names)
        ]
        assert len(_detect(rows)) == 1

    def test_renamed_payment_continues(self) -> None:
        old = [
            described(
                _month(date(2025, 2, 15), i),
                -830,
                f"WWW.SHOPMART.* {c}",
                foreign=(699, "GBP"),
            )
            for i, c in enumerate("QWERTY")
        ]
        new = [
            described(
                _month(date(2025, 8, 15), i),
                -815,
                f"Shopmart Prime*{c}",
                foreign=(699, "GBP"),
            )
            for i, c in enumerate("ASD")
        ]
        [series] = _detect(old + new)
        assert series.name.startswith("Shopmart Prime")
        assert len(series.charges) == 9

    def test_unrelated_payments_at_one_price_stay_apart(self) -> None:
        old = _monthly("EXAMPLE STREAM", [999] * 5)
        new = _monthly("OTHER MUSIC", [999] * 4, start=date(2025, 7, 10))
        assert len(_detect(old + new)) == 2


class TestOtherCadences:
    def test_annual_payment(self) -> None:
        rows = [
            described(date(2025, 2, 12), -12500, "BROADCAST LICENCE"),
            described(date(2026, 3, 4), -12500, "BROADCAST LICENCE"),
        ]
        [series] = _detect(rows)
        assert (series.cadence.name, series.monthly_minor) == ("annual", 1042)

    def test_quarterly_fee_of_varying_amount(self) -> None:
        days = [
            date(2025, 3, 27),
            date(2025, 6, 27),
            date(2025, 9, 26),
            date(2025, 12, 29),
        ]
        rows = [
            described(day, -amount, "FEE-QTR", channel="fee")
            for day, amount in zip(days, [2800, 2150, 2900, 2400], strict=True)
        ]
        [series] = _detect(rows)
        assert (series.cadence.name, series.fixed, series.changes) == (
            "quarterly",
            False,
            (),
        )


class TestStatus:
    def test_stopped_once_a_charge_is_well_overdue(self) -> None:
        rows = _monthly("EXAMPLE STREAM", [1299] * 6)
        last = rows[-1].posted_on
        assert _detect(rows, as_of=last + timedelta(days=50))[0].status == "active"
        assert _detect(rows, as_of=last + timedelta(days=56))[0].status == "stopped"


class TestReport:
    def test_changes_starts_stops_and_monthly_commitments(self) -> None:
        loan = _monthly(
            "EXAMPLE LENDER",
            [98750] * 8 + [110600],
            start=date(2026, 1, 10),
            channel="direct_debit",
        )
        started = _monthly("EXAMPLE ASSISTANT", [2000] * 3, start=date(2026, 7, 11))
        stopped = _monthly("OLD STREAM", [999] * 6, start=date(2026, 1, 1))
        ancient = _monthly("ANCIENT", [500] * 4, start=date(2025, 1, 1))
        report = build_report(
            loan + started + stopped + ancient,
            currency="EUR",
            as_of=date(2026, 9, 11),
            window_days=90,
        )
        assert [change.after_minor for _, change in report.changed()] == [110600]
        assert [s.name for s in report.started()] == ["EXAMPLE ASSISTANT"]
        assert [s.name for s in report.stopped_recently()] == ["OLD STREAM"]
        assert report.monthly_minor("out") == 110600 + 2000

    def test_no_transactions(self) -> None:
        with pytest.raises(ValueError, match="import"):
            build_report([], currency="EUR")
