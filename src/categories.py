"""Which category each transaction belongs to, worked out on every read.

Nothing here is stored. The owner's decisions are: a label on one transaction,
or a confirmed rule for a counterparty key. Everything else follows from them
and from the channel, so correcting one rule recategorises all history at once.

Precedence, first match wins:

1. The transaction's label.
2. The active rule for its counterparty key, if confirmed. A rejected rule
   leaves it unclassified, overriding the channel default.
3. The channel's default: cash withdrawals are cash, bank charges are fees.
4. Unclassified, which is always reported as such and never folded away.

Proposed rules never apply; they wait for review.

Public API:
    CATEGORIES        -- slug → label, in report order
    UNCLASSIFIED      -- the slug reports use for rows nothing names
    validate_category -- check a slug, or None for an explicit "none"
    Categorised       -- a transaction with its category and why
    categorise        -- apply labels, rules and channel defaults
    CategoryTotal     -- money out and in for one category
    totals            -- per-category totals over a date range

Example:
    from categories import categorise, totals

    rows = categorise(described, rules=rules, labels=labels)
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from datetime import date

from models import DescribedTransaction

CATEGORIES: dict[str, str] = {
    "housing": "Housing",
    "childcare": "Childcare",
    "car": "Car",
    "groceries": "Groceries",
    "eating-out": "Eating out and coffee",
    "shopping": "Shopping",
    "subscriptions": "Subscriptions and digital",
    "health": "Health and medical",
    "travel": "Travel and holidays",
    "kids-family": "Kids and family",
    "pets": "Pets",
    "personal-care": "Personal care",
    "fees": "Fees and interest",
    "cash": "Cash",
    "transfer-household": "Transfers: household",
    "transfer-friends": "Transfers: friends and repayments",
    "transfer-savings": "Transfers: savings and investments",
    "gifts-charity": "Gifts and charity",
    "government-tax": "Government and tax",
    "income-salary": "Income: salary",
    "income-other": "Income: other",
}
"""Spending categories first, transfers and income last. One per transaction."""

UNCLASSIFIED = "unclassified"

CHANNEL_DEFAULTS: dict[str, str] = {"atm": "cash", "fee": "fees"}
"""Channels whose category the bank's own text already settles."""


def validate_category(slug: str) -> str | None:
    """Return *slug* if it is a known category, or None for ``none``.

    ``none`` is how the owner says a payee or payment has no category, so it
    stays unclassified.

    Raises:
        ValueError: If the slug is unknown; the message lists the known ones.
    """
    if slug == "none":
        return None
    if slug not in CATEGORIES:
        raise ValueError(
            f"Unknown category {slug!r}. Use one of: {', '.join(CATEGORIES)}, "
            f"or 'none' to leave it unclassified."
        )
    return slug


@dataclass(frozen=True)
class Categorised:
    """A transaction with its category.

    Attributes:
        transaction: The described transaction.
        category: A slug from ``CATEGORIES``, or ``UNCLASSIFIED``.
        basis: What decided it: ``label``, ``rule``, ``channel`` or ``none``.
    """

    transaction: DescribedTransaction
    category: str
    basis: str


def categorise(
    rows: Iterable[DescribedTransaction],
    *,
    rules: Mapping[str, str | None],
    labels: Mapping[int, str | None],
) -> list[Categorised]:
    """Give every transaction one category.

    Args:
        rows: Described transactions.
        rules: Counterparty key → category for confirmed rules, or None for
            rejected ones. Proposed rules must not be passed.
        labels: Transaction id → category for the owner's labels, or None for
            a label saying "no category".

    Returns:
        One ``Categorised`` per row, in the order given.
    """
    result: list[Categorised] = []
    for row in rows:
        if row.transaction_id in labels:
            category, basis = labels[row.transaction_id], "label"
        elif row.counterparty_key in rules:
            category, basis = rules[row.counterparty_key], "rule"
        elif row.channel in CHANNEL_DEFAULTS:
            category, basis = CHANNEL_DEFAULTS[row.channel], "channel"
        else:
            category, basis = None, "none"
        result.append(Categorised(row, category or UNCLASSIFIED, basis))
    return result


@dataclass(frozen=True)
class CategoryTotal:
    """Money moved in one category over a period, in minor units.

    Attributes:
        category: Slug, or ``UNCLASSIFIED``.
        out_minor: Total leaving the account, as a positive number.
        in_minor: Total arriving: refunds, repayments, income.
        payments: Number of transactions.
    """

    category: str
    out_minor: int
    in_minor: int
    payments: int

    @property
    def net_out_minor(self) -> int:
        """Money out less money in: a refund reduces what a category cost."""
        return self.out_minor - self.in_minor


def totals(
    rows: Iterable[Categorised],
    *,
    start: date | None = None,
    end: date | None = None,
) -> list[CategoryTotal]:
    """Total each category over ``start``–``end`` inclusive.

    Returns:
        One total per category that moved money, in ``CATEGORIES`` order, with
        unclassified last.
    """
    sums: dict[str, list[int]] = {}
    for item in rows:
        day = item.transaction.posted_on
        if (start and day < start) or (end and day > end):
            continue
        entry = sums.setdefault(item.category, [0, 0, 0])
        amount = item.transaction.amount_minor
        if amount < 0:
            entry[0] -= amount
        else:
            entry[1] += amount
        entry[2] += 1
    order = [*CATEGORIES, UNCLASSIFIED]
    return [CategoryTotal(slug, *sums[slug]) for slug in order if slug in sums]
