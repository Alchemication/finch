"""Categories: precedence, totals, and the rules and labels behind them.

Every payee, amount and date here is invented.
"""

from __future__ import annotations

import sqlite3
from datetime import date

import pytest

from categories import (
    UNCLASSIFIED,
    CategoryTotal,
    categorise,
    totals,
    validate_category,
)
from store import (
    add_category_rule,
    add_transaction_label,
    load_category_rules,
)
from tests.factories import described


class TestValidateCategory:
    def test_known_slug(self) -> None:
        assert validate_category("groceries") == "groceries"

    def test_none_means_unclassified(self) -> None:
        assert validate_category("none") is None

    def test_unknown_slug_lists_the_known_ones(self) -> None:
        with pytest.raises(ValueError, match="groceries"):
            validate_category("food")


class TestCategorise:
    def test_rule_names_every_payment_of_a_payee(self) -> None:
        rows = [
            described("2026-03-02", -4210, "EXAMPLE GROCER"),
            described("2026-03-09", -5175, "EXAMPLE GROCER"),
        ]
        result = categorise(rows, rules={"EXAMPLEGROCER": "groceries"}, labels={})
        assert [item.category for item in result] == ["groceries", "groceries"]
        assert {item.basis for item in result} == {"rule"}

    def test_label_wins_over_rule(self) -> None:
        odd = described("2026-03-16", -24900, "EXAMPLE GROCER")
        result = categorise(
            [odd],
            rules={"EXAMPLEGROCER": "groceries"},
            labels={odd.transaction_id: "kids-family"},
        )
        assert result[0].category == "kids-family"
        assert result[0].basis == "label"

    def test_channel_default_for_cash_and_fees(self) -> None:
        rows = [
            described("2026-03-03", -10000, "EXAMPLE TOWN", channel="atm"),
            described("2026-03-31", -600, "ACCOUNT FEE", channel="fee"),
        ]
        result = categorise(rows, rules={}, labels={})
        assert [item.category for item in result] == ["cash", "fees"]

    def test_rejected_rule_overrides_channel_default(self) -> None:
        withdrawal = described("2026-03-03", -10000, "EXAMPLE TOWN", channel="atm")
        result = categorise([withdrawal], rules={"EXAMPLETOWN": None}, labels={})
        assert result[0].category == UNCLASSIFIED

    def test_label_of_none_leaves_it_unclassified(self) -> None:
        row = described("2026-03-02", -4210, "EXAMPLE GROCER")
        result = categorise(
            [row],
            rules={"EXAMPLEGROCER": "groceries"},
            labels={row.transaction_id: None},
        )
        assert result[0].category == UNCLASSIFIED

    def test_nothing_known_is_unclassified(self) -> None:
        result = categorise(
            [described("2026-03-02", -999, "UNKNOWN SHOP")], rules={}, labels={}
        )
        assert result[0].category == UNCLASSIFIED
        assert result[0].basis == "none"


class TestTotals:
    def test_refund_reduces_net_and_unclassified_comes_last(self) -> None:
        rows = categorise(
            [
                described("2026-03-02", -2000, "UNKNOWN SHOP"),
                described("2026-03-05", -8999, "EXAMPLE STORE"),
                described("2026-03-12", 8999, "EXAMPLE STORE"),
                described("2026-03-20", -3150, "EXAMPLE GROCER"),
            ],
            rules={"EXAMPLESTORE": "shopping", "EXAMPLEGROCER": "groceries"},
            labels={},
        )
        result = totals(rows)
        assert result == [
            CategoryTotal("groceries", 3150, 0, 1),
            CategoryTotal("shopping", 8999, 8999, 2),
            CategoryTotal(UNCLASSIFIED, 2000, 0, 1),
        ]
        assert result[1].net_out_minor == 0

    def test_date_range_is_inclusive(self) -> None:
        rows = categorise(
            [
                described("2026-02-28", -100, "EXAMPLE GROCER"),
                described("2026-03-01", -200, "EXAMPLE GROCER"),
                described("2026-03-31", -300, "EXAMPLE GROCER"),
                described("2026-04-01", -400, "EXAMPLE GROCER"),
            ],
            rules={"EXAMPLEGROCER": "groceries"},
            labels={},
        )
        march = totals(rows, start=date(2026, 3, 1), end=date(2026, 3, 31))
        assert march == [CategoryTotal("groceries", 500, 0, 2)]

    def test_empty(self) -> None:
        assert totals([]) == []


class TestCategoryRuleStore:
    def test_decision_supersedes_proposal(self, conn: sqlite3.Connection) -> None:
        proposal = add_category_rule(
            conn,
            counterparty_key="EXAMPLEGROCER",
            category="shopping",
            source="claude",
            status="proposed",
            confidence="medium",
        )
        decision = add_category_rule(
            conn,
            counterparty_key="EXAMPLEGROCER",
            category="groceries",
            source="owner",
            status="confirmed",
        )
        active = load_category_rules(conn)
        assert [(r["id"], r["category"], r["source"]) for r in active] == [
            (decision, "groceries", "owner")
        ]
        superseded = conn.execute(
            "SELECT superseded_by FROM category_rules WHERE id = ?", (proposal,)
        ).fetchone()[0]
        assert superseded == decision

    def test_rejected_rule_has_no_category(self, conn: sqlite3.Connection) -> None:
        add_category_rule(
            conn,
            counterparty_key="EXAMPLETOWN",
            category=None,
            source="owner",
            status="rejected",
        )
        assert load_category_rules(conn)[0]["category"] is None

    def test_rejected_needs_no_category_and_others_need_one(
        self, conn: sqlite3.Connection
    ) -> None:
        with pytest.raises(sqlite3.IntegrityError):
            add_category_rule(
                conn,
                counterparty_key="EXAMPLETOWN",
                category=None,
                source="owner",
                status="confirmed",
            )

    def test_label_for_unknown_transaction(self, conn: sqlite3.Connection) -> None:
        with pytest.raises(ValueError, match="category unclassified"):
            add_transaction_label(conn, 999, "groceries")
