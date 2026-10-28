"""The ledger as the annotation page and the category commands see it.

Loads every account's transactions with their categories, groups them by
payee, and applies the owner's decisions. The page (``ui_server``) and the CLI
(``cmd_categories``) both go through here, so a decision made in either is
the same row in ``category_rules`` or ``transaction_labels``.

Money crosses to the page as integer minor units for sorting and bar widths,
and as text formatted here for display. The page never adds amounts itself.

Public API:
    load_ledger          -- every transaction, categorised, and the currency
    Payee                -- what one counterparty key amounts to
    group_payees         -- transactions grouped by counterparty key
    page_state           -- everything the page shows on load
    payee_transactions   -- one payee's transactions
    decide_payee         -- the owner's category for a payee, or none
    confirm_proposals    -- turn proposals into the owner's rules
    label_transactions   -- the owner's category for single payments

Example:
    from annotate import page_state

    state = page_state(conn)
"""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass, field
from datetime import date

from categories import (
    CATEGORIES,
    UNCLASSIFIED,
    Categorised,
    categorise,
    totals,
    validate_category,
)
from describe import describe_account
from money import format_minor
from store import (
    add_category_rule,
    add_transaction_label,
    load_accounts,
    load_category_rules,
    load_transaction_labels,
)


def load_ledger(conn: sqlite3.Connection) -> tuple[list[Categorised], str]:
    """Categorise every transaction of every account.

    Returns:
        The categorised transactions, oldest first, and their currency.

    Raises:
        ValueError: If there are no transactions, or accounts in several
            currencies, which one total cannot add up.
    """
    accounts = load_accounts(conn)
    currencies = {account.currency for account in accounts}
    if len(currencies) > 1:
        raise ValueError(
            f"Accounts are in several currencies ({', '.join(sorted(currencies))}); "
            f"category totals add up one currency only."
        )
    described = [row for a in accounts for row in describe_account(conn, a.id)]
    if not described:
        raise ValueError(
            "The ledger has no transactions. Import an export first with "
            "'uv run python main.py import FILE'."
        )
    described.sort(key=lambda row: (row.posted_on, row.transaction_id))
    rules = {
        row["counterparty_key"]: row["category"]
        for row in load_category_rules(conn)
        if row["status"] != "proposed"
    }
    labels = {
        tid: row["category"] for tid, row in load_transaction_labels(conn).items()
    }
    return categorise(described, rules=rules, labels=labels), currencies.pop()


@dataclass
class Payee:
    """What one counterparty key amounts to.

    Attributes:
        key: The counterparty key.
        name: The latest text the bank printed for it.
        channels: Channels seen, most frequent first.
        payments: Number of transactions.
        out_minor: Money out, positive.
        in_minor: Money in.
        first: Earliest posting date.
        last: Latest posting date.
        categories: Payments per category, to spot a payee whose payments
            were labelled differently.
    """

    key: str
    name: str = ""
    channels: list[str] = field(default_factory=list)
    payments: int = 0
    out_minor: int = 0
    in_minor: int = 0
    first: date | None = None
    last: date | None = None
    categories: dict[str, int] = field(default_factory=dict)


def group_payees(rows: list[Categorised]) -> dict[str, Payee]:
    """Group transactions by counterparty key, naming each by its latest text."""
    payees: dict[str, Payee] = {}
    channel_counts: dict[str, dict[str, int]] = {}
    for item in sorted(rows, key=lambda r: r.transaction.posted_on):
        tx = item.transaction
        payee = payees.setdefault(tx.counterparty_key, Payee(tx.counterparty_key))
        counts = channel_counts.setdefault(tx.counterparty_key, {})
        counts[tx.channel] = counts.get(tx.channel, 0) + 1
        payee.name = tx.counterparty
        payee.payments += 1
        payee.first = payee.first or tx.posted_on
        payee.last = tx.posted_on
        payee.categories[item.category] = payee.categories.get(item.category, 0) + 1
        if tx.amount_minor < 0:
            payee.out_minor -= tx.amount_minor
        else:
            payee.in_minor += tx.amount_minor
    for key, counts in channel_counts.items():
        payees[key].channels = sorted(counts, key=lambda c: -counts[c])
    return payees


def _money(minor: int, currency: str) -> dict[str, object]:
    return {"minor": minor, "text": format_minor(minor, currency)}


def page_state(conn: sqlite3.Connection) -> dict[str, object]:
    """Everything the annotation page shows on load.

    Returns:
        Categories, payees with their category and any pending proposal,
        coverage, and per-year and per-month totals by category.
    """
    rows, currency = load_ledger(conn)
    payees = group_payees(rows)
    rules = {row["counterparty_key"]: row for row in load_category_rules(conn)}

    payee_list = []
    for payee in payees.values():
        rule = rules.get(payee.key)
        proposal = None
        decided = None
        if rule is not None and rule["status"] == "proposed":
            proposal = {
                "category": rule["category"],
                "confidence": rule["confidence"],
                "note": rule["note"],
            }
        elif rule is not None:
            decided = rule["category"] or "none"
        main = max(payee.categories, key=lambda c: payee.categories[c])
        payee_list.append(
            {
                "key": payee.key,
                "name": payee.name.strip(),
                "channel": payee.channels[0],
                "payments": payee.payments,
                "out": _money(payee.out_minor, currency),
                "in": _money(payee.in_minor, currency),
                "moved_minor": payee.out_minor + payee.in_minor,
                "first": payee.first.isoformat() if payee.first else None,
                "last": payee.last.isoformat() if payee.last else None,
                "category": main,
                "mixed": len(payee.categories) > 1,
                "decided": decided,
                "proposal": proposal,
            }
        )
    payee_list.sort(key=lambda p: -int(p["moved_minor"]))  # type: ignore[call-overload]

    out_total = sum(
        -i.transaction.amount_minor for i in rows if i.transaction.amount_minor < 0
    )
    out_unclassified = sum(
        -i.transaction.amount_minor
        for i in rows
        if i.transaction.amount_minor < 0 and i.category == UNCLASSIFIED
    )
    first = rows[0].transaction.posted_on
    last = rows[-1].transaction.posted_on
    years = [
        _period(
            rows,
            currency,
            str(year),
            max(first, date(year, 1, 1)),
            min(last, date(year, 12, 31)),
        )
        for year in range(first.year, last.year + 1)
    ]
    years.append(_period(rows, currency, "All", first, last))
    months = []
    year, month = first.year, first.month
    while (year, month) <= (last.year, last.month):
        nxt = date(year + month // 12, month % 12 + 1, 1)
        start, end = date(year, month, 1), date.fromordinal(nxt.toordinal() - 1)
        months.append(
            {
                "label": f"{year}-{month:02d}",
                "totals": _totals_json(totals(rows, start=start, end=end), currency),
            }
        )
        year, month = nxt.year, nxt.month

    return {
        "currency": currency,
        "from": first.isoformat(),
        "to": last.isoformat(),
        "categories": [{"slug": s, "label": label} for s, label in CATEGORIES.items()],
        "payees": payee_list,
        "coverage": {
            "out": _money(out_total, currency),
            "unclassified": _money(out_unclassified, currency),
            "classified_permille": (
                (out_total - out_unclassified) * 1000 // out_total if out_total else 0
            ),
            "proposals": sum(1 for p in payee_list if p["proposal"]),
            "transactions": len(rows),
            "unclassified_transactions": sum(
                1 for i in rows if i.category == UNCLASSIFIED
            ),
        },
        "years": years,
        "months": months,
    }


SPENDING_EXCLUDED_PREFIXES: tuple[str, ...] = ("transfer-", "income-")
"""Categories that move money without spending it: transfers and income."""


def is_spending(category: str) -> bool:
    """Whether a category counts as spending (unclassified does, until named)."""
    return not category.startswith(SPENDING_EXCLUDED_PREFIXES)


def _period(
    rows: list[Categorised], currency: str, label: str, start: date, end: date
) -> dict[str, object]:
    """Totals for one period, with the headline figures the page shows."""
    items = totals(rows, start=start, end=end)
    # Unclassified money in is not a refund of anything: count its money out only.
    spend = sum(
        t.out_minor if t.category == UNCLASSIFIED else t.net_out_minor
        for t in items
        if is_spending(t.category)
    )
    unclassified = next((t.out_minor for t in items if t.category == UNCLASSIFIED), 0)
    named = [t for t in items if is_spending(t.category) and t.category != UNCLASSIFIED]
    top = max(named, key=lambda t: t.net_out_minor, default=None)
    days = (end - start).days + 1
    return {
        "label": label,
        "from": start.isoformat(),
        "to": end.isoformat(),
        "partial": label != "All"
        and (start.month, start.day, end.month, end.day) != (1, 1, 12, 31),
        "days": days,
        "spend": _money(spend, currency),
        "spend_per_month": _money(spend * 30 // days if days else 0, currency),
        "unclassified_out": _money(unclassified, currency),
        "money_in": _money(sum(t.in_minor for t in items), currency),
        "top": (
            {"category": top.category, "net_out": _money(top.net_out_minor, currency)}
            if top
            else None
        ),
        "totals": _totals_json(items, currency),
    }


def _totals_json(items: list, currency: str) -> list[dict[str, object]]:  # type: ignore[type-arg]
    return [
        {
            "category": t.category,
            "net_out": _money(t.net_out_minor, currency),
            "out": _money(t.out_minor, currency),
            "in": _money(t.in_minor, currency),
            "payments": t.payments,
        }
        for t in items
    ]


def payee_transactions(conn: sqlite3.Connection, key: str) -> list[dict[str, object]]:
    """One payee's transactions, newest first, with each one's category and label.

    Raises:
        ValueError: If no transaction has that counterparty key.
    """
    rows, currency = load_ledger(conn)
    labels = load_transaction_labels(conn)
    chosen = [item for item in rows if item.transaction.counterparty_key == key]
    if not chosen:
        raise ValueError(f"No transactions for payee {key!r}.")
    result = []
    for item in reversed(chosen):
        tx = item.transaction
        label = labels.get(tx.transaction_id)
        result.append(
            {
                "id": tx.transaction_id,
                "date": tx.posted_on.isoformat(),
                "amount": _money(tx.amount_minor, currency),
                "foreign": (
                    format_minor(tx.foreign_amount_minor, tx.foreign_currency)
                    if tx.foreign_amount_minor is not None and tx.foreign_currency
                    else None
                ),
                "channel": tx.channel,
                "text": tx.counterparty.strip(),
                "category": item.category,
                "basis": item.basis,
                "note": label["note"] if label is not None else None,
            }
        )
    return result


def _known_keys(conn: sqlite3.Connection) -> set[str]:
    rows, _ = load_ledger(conn)
    return {item.transaction.counterparty_key for item in rows}


def decide_payee(
    conn: sqlite3.Connection, key: str, category: str, note: str | None = None
) -> None:
    """Record the owner's category for a payee; ``none`` leaves it unclassified.

    Raises:
        ValueError: On an unknown category or payee.
    """
    slug = validate_category(category)
    if key not in _known_keys(conn):
        raise ValueError(
            f"No transaction has the counterparty key {key!r}. Keys are shown "
            f"by 'category unclassified' and 'category review'."
        )
    with conn:
        add_category_rule(
            conn,
            counterparty_key=key,
            category=slug,
            source="owner",
            status="confirmed" if slug else "rejected",
            note=note,
        )


def confirm_proposals(
    conn: sqlite3.Connection,
    *,
    keys: list[str] | None = None,
    categories: list[str] | None = None,
    every: bool = False,
    exclude: list[str] | None = None,
) -> int:
    """Turn pending proposals into the owner's rules.

    Args:
        conn: Open ledger connection.
        keys: Confirm these payees' proposals.
        categories: Confirm every proposal in these categories.
        every: Confirm all proposals.
        exclude: Payees to hold back.

    Returns:
        How many were confirmed.

    Raises:
        ValueError: If nothing says what to confirm.
    """
    if not (every or keys or categories):
        raise ValueError("Say what to confirm: --category SLUG, --key KEY or --all.")
    held = set(exclude or [])
    chosen = [
        row
        for row in load_category_rules(conn)
        if row["status"] == "proposed"
        and row["counterparty_key"] not in held
        and (
            every
            or row["category"] in (categories or [])
            or row["counterparty_key"] in (keys or [])
        )
    ]
    with conn:
        for row in chosen:
            add_category_rule(
                conn,
                counterparty_key=row["counterparty_key"],
                category=row["category"],
                source="owner",
                status="confirmed",
                note=f"Confirmed proposal #{row['id']}",
            )
    return len(chosen)


def label_transactions(
    conn: sqlite3.Connection, ids: list[int], category: str, note: str | None = None
) -> None:
    """Record the owner's category for single payments; ``none`` clears it to none.

    Raises:
        ValueError: On an unknown category or transaction; nothing is written.
    """
    slug = validate_category(category)
    with conn:
        for transaction_id in ids:
            add_transaction_label(conn, transaction_id, slug, note)
