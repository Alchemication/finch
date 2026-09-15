"""Recurring payments, derived from the ledger on every read.

A recurring payment is a run of charges at a regular cadence: a subscription,
a direct debit, a monthly transfer, a salary. Nothing here is stored. Series
are recomputed from transactions each time, so a newly imported month or a
better rule changes the answer everywhere, with no stale copy to reconcile.

How a series is found:

1. Rows group by channel, direction and counterparty key. Transfers group by
   channel and direction alone, because their references are typed per
   payment: one real monthly transfer used eleven references. A key that is a
   truncation of exactly one longer key joins it.
2. An exact amount charged more than ``HABITUAL_CHARGES_PER_MONTH`` times per
   month within a group is a habit and is set aside.
3. Charges chain oldest first. Each joins the chain whose last charge is at
   least ``RECURRING_MIN_GAP_DAYS`` earlier and closest in price, within a
   tolerance. That splits several subscriptions from one merchant and lets a
   price rise continue its own series.
4. A chain is a series when its gaps fit a cadence and its amounts are fixed,
   or allowed to vary for its channel or for a rarely charged counterparty.
   An annual series must be fixed: two varying charges a year apart are chance.
5. A series ending where another begins, at the same price and cadence under
   a similar name, is one payment renamed.

Prices compare in the currency the merchant charged when the bank reports it,
so exchange-rate movement on a dollar subscription is not a price change.

Public API:
    detect_series   -- every recurring series in an account's transactions
    build_report    -- series plus what changed, started and stopped recently
    Series          -- one recurring payment and its charges
    PriceChange     -- a sustained change in a series' price
    RecurringReport -- what ``main.py recurring`` renders
    CADENCES        -- the cadences a series can have

Example:
    from describe import describe_account
    from recurring import build_report

    report = build_report(describe_account(conn, account.id), currency="EUR")
"""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from datetime import date, timedelta
from difflib import SequenceMatcher
from fractions import Fraction
from itertools import pairwise

from config import (
    ANNUAL_GAP_DAYS,
    ANNUAL_MIN_AMOUNT_MINOR,
    ANNUAL_MIN_CHARGES,
    FIXED_AMOUNT_SHARE_PCT,
    HABITUAL_CHARGES_PER_MONTH,
    MONTHLY_GAP_DAYS,
    PRICE_CHANGE_MIN_PCT,
    QUARTERLY_GAP_DAYS,
    RECURRING_AMOUNT_TOLERANCE_PCT,
    RECURRING_GRACE_DAYS,
    RECURRING_MIN_CHARGES,
    RECURRING_MIN_GAP_DAYS,
    RECURRING_ON_TIME_SHARE_PCT,
    RECURRING_REGULAR_SHARE_PCT,
    RECURRING_REPORT_WINDOW_DAYS,
    RECURRING_VARIABLE_TOLERANCE_PCT,
    RENAME_MIN_COMMON_CHARS,
    TRUNCATED_KEY_MIN_CHARS,
)
from models import DescribedTransaction

EXCLUDED_CHANNELS: frozenset[str] = frozenset({"atm"})
"""Cash withdrawals repeat by habit, and what the cash bought is unknown."""

GROUPED_BY_CHANNEL: frozenset[str] = frozenset({"transfer_in", "transfer_out"})
"""Channels whose counterparty text is a per-payment reference, not a name."""

VARIABLE_CHANNELS: frozenset[str] = frozenset({"direct_debit", "fee", "transfer_in"})
"""Channels whose recurring amounts legitimately vary: bills, bank fees, pay."""

WIDE_TOLERANCE_CHANNELS: frozenset[str] = frozenset({"direct_debit", "fee"})
"""Channels whose consecutive charges may step by up to the variable tolerance.

Not incoming transfers: grouped by channel alone, a real salary chain compared
by the wide band drifted charge by charge into a refund and two unrelated
credits, each step within the band of the one before.
"""

INCOMING_CHANNELS: frozenset[str] = frozenset({"transfer_in"})
"""Channels where money coming in can recur. A card credit is a refund."""

Price = tuple[str, int]
"""Currency and amount in minor units, as the merchant charged it."""


@dataclass(frozen=True)
class Cadence:
    """How often a series charges.

    Attributes:
        name: ``monthly``, ``quarterly`` or ``annual``.
        min_days: Shortest on-time gap.
        max_days: Longest on-time gap.
        max_skipped: Missed periods a single gap may contain.
        min_charges: Charges needed before a chain counts.
        months: Months per period, for monthly equivalents.
    """

    name: str
    min_days: int
    max_days: int
    max_skipped: int
    min_charges: int
    months: int


CADENCES: tuple[Cadence, ...] = (
    Cadence("monthly", *MONTHLY_GAP_DAYS, 1, RECURRING_MIN_CHARGES, 1),
    Cadence("quarterly", *QUARTERLY_GAP_DAYS, 0, RECURRING_MIN_CHARGES, 3),
    Cadence("annual", *ANNUAL_GAP_DAYS, 0, ANNUAL_MIN_CHARGES, 12),
)
"""Tried in this order; the first that fits a chain wins."""


@dataclass(frozen=True)
class PriceChange:
    """A change in a series' established price.

    Attributes:
        on: Date of the first charge at the new price.
        before_minor: The established price.
        after_minor: The new price.
        currency: Currency of both prices.
        confirmed: A later charge repeated the new price. False when the change
            is on the latest charge, so it could still be a one-off.
    """

    on: date
    before_minor: int
    after_minor: int
    currency: str
    confirmed: bool


@dataclass(frozen=True)
class Series:
    """One recurring payment.

    Attributes:
        channel: Channel of its charges.
        direction: ``out`` or ``in``.
        cadence: How often it charges.
        charges: Its transactions, oldest first.
        currency: The account's currency.
        fixed: Most consecutive charges were the same price.
        status: ``active``, or ``stopped`` once a charge is overdue past grace.
        changes: Sustained price changes, oldest first. Empty when the amount
            varies, since every charge would then read as a change.
    """

    channel: str
    direction: str
    cadence: Cadence
    charges: tuple[DescribedTransaction, ...]
    currency: str
    fixed: bool
    status: str
    changes: tuple[PriceChange, ...]

    @property
    def name(self) -> str:
        """The counterparty as printed on the latest charge."""
        return self.charges[-1].counterparty

    @property
    def names(self) -> tuple[str, ...]:
        """Every distinct counterparty text, in order of first use."""
        return tuple(dict.fromkeys(charge.counterparty for charge in self.charges))

    @property
    def first(self) -> date:
        """Date of the first charge."""
        return self.charges[0].posted_on

    @property
    def last(self) -> date:
        """Date of the latest charge."""
        return self.charges[-1].posted_on

    @property
    def price_currency(self) -> str:
        """Currency the latest charge was priced in."""
        return _price(self.charges[-1], self.currency)[0]

    @property
    def current_price_minor(self) -> int:
        """Latest price in ``price_currency``."""
        return _price(self.charges[-1], self.currency)[1]

    @property
    def current_minor(self) -> int:
        """Latest charge in the account's currency, unsigned."""
        return abs(self.charges[-1].amount_minor)

    @property
    def monthly_minor(self) -> int:
        """Latest charge spread over the months of one period, rounded."""
        months = self.cadence.months
        return (self.current_minor + months // 2) // months


@dataclass(frozen=True)
class RecurringReport:
    """Series and what changed about them within a window.

    Attributes:
        as_of: The ledger's latest transaction date, not today, so a stale
            ledger does not report every payment as stopped.
        since: Start of the window.
        series: Every series, active first.
    """

    as_of: date
    since: date
    series: tuple[Series, ...]

    @property
    def active(self) -> tuple[Series, ...]:
        """Series still charging."""
        return tuple(s for s in self.series if s.status == "active")

    @property
    def stopped(self) -> tuple[Series, ...]:
        """Series whose charges have stopped."""
        return tuple(s for s in self.series if s.status == "stopped")

    def changed(self) -> list[tuple[Series, PriceChange]]:
        """Price changes on or after ``since``, newest first."""
        found = [(s, c) for s in self.series for c in s.changes if c.on >= self.since]
        return sorted(found, key=lambda item: item[1].on, reverse=True)

    def started(self) -> list[Series]:
        """Active series whose first charge is on or after ``since``."""
        return [s for s in self.active if s.first >= self.since]

    def stopped_recently(self) -> list[Series]:
        """Stopped series that became overdue on or after ``since``."""
        return [
            s
            for s in self.stopped
            if s.last + timedelta(days=s.cadence.max_days + RECURRING_GRACE_DAYS)
            >= self.since
        ]

    def monthly_minor(self, direction: str) -> int:
        """Monthly equivalent of every active series in one direction."""
        return sum(s.monthly_minor for s in self.active if s.direction == direction)


def _price(row: DescribedTransaction, currency: str) -> Price:
    if row.foreign_currency is not None and row.foreign_amount_minor is not None:
        return row.foreign_currency, row.foreign_amount_minor
    return currency, abs(row.amount_minor)


def _same_price(a: Price, b: Price) -> bool:
    if a[0] != b[0]:
        return False
    return abs(a[1] - b[1]) * 100 < PRICE_CHANGE_MIN_PCT * max(a[1], b[1], 1)


def _order(row: DescribedTransaction) -> tuple[date, int]:
    return row.posted_on, row.transaction_id


def _per_month(rows: Sequence[DescribedTransaction]) -> Fraction:
    months = {(row.posted_on.year, row.posted_on.month) for row in rows}
    return Fraction(len(rows), len(months))


def _truncation_target(key: str, keys: set[str]) -> str:
    if len(key) < TRUNCATED_KEY_MIN_CHARS:
        return key
    longer = [other for other in keys if other != key and other.startswith(key)]
    return longer[0] if len(longer) == 1 else key


def _group(rows: Iterable[DescribedTransaction]) -> dict[tuple[str, str, str], list]:
    raw: dict[tuple[str, str, str], list[DescribedTransaction]] = defaultdict(list)
    for row in rows:
        direction = "in" if row.amount_minor > 0 else "out"
        key = "" if row.channel in GROUPED_BY_CHANNEL else row.counterparty_key
        raw[(row.channel, direction, key)].append(row)
    keys_by_scope: dict[tuple[str, str], set[str]] = defaultdict(set)
    for channel, direction, key in raw:
        keys_by_scope[(channel, direction)].add(key)
    merged: dict[tuple[str, str, str], list[DescribedTransaction]] = defaultdict(list)
    for (channel, direction, key), items in raw.items():
        target = _truncation_target(key, keys_by_scope[(channel, direction)])
        merged[(channel, direction, target)].extend(items)
    return {group: sorted(items, key=_order) for group, items in merged.items()}


def _without_habits(rows: Sequence[DescribedTransaction], currency: str) -> list:
    by_price: dict[Price, list[DescribedTransaction]] = defaultdict(list)
    for row in rows:
        by_price[_price(row, currency)].append(row)
    kept = [
        row
        for same in by_price.values()
        if _per_month(same) <= HABITUAL_CHARGES_PER_MONTH
        for row in same
    ]
    return sorted(kept, key=_order)


def _chain(
    rows: Sequence[DescribedTransaction], currency: str, tolerance_pct: int
) -> list[list]:
    chains: list[list[DescribedTransaction]] = []
    for row in rows:
        row_currency, amount = _price(row, currency)
        best: list[DescribedTransaction] | None = None
        best_rank: tuple[Fraction, int, int] | None = None
        for chain in chains:
            last = chain[-1]
            last_currency, last_amount = _price(last, currency)
            if last_currency != row_currency or last_amount == 0:
                continue
            if (row.posted_on - last.posted_on).days < RECURRING_MIN_GAP_DAYS:
                continue
            difference = Fraction(abs(amount - last_amount), last_amount)
            if difference * 100 > tolerance_pct:
                continue
            rank = (difference, -len(chain), -last.posted_on.toordinal())
            if best_rank is None or rank < best_rank:
                best, best_rank = chain, rank
        if best is None:
            chains.append([row])
        else:
            best.append(row)
    return chains


def _cadence(dates: Sequence[date]) -> Cadence | None:
    gaps = [(later - earlier).days for earlier, later in pairwise(dates)]
    for cadence in CADENCES:
        if len(dates) < cadence.min_charges or not gaps:
            continue
        on_time = sum(1 for gap in gaps if cadence.min_days <= gap <= cadence.max_days)
        regular = sum(
            1
            for gap in gaps
            if any(
                cadence.min_days * periods <= gap <= cadence.max_days * periods
                for periods in range(1, cadence.max_skipped + 2)
            )
        )
        if on_time * 100 < RECURRING_ON_TIME_SHARE_PCT * len(gaps):
            continue
        if regular * 100 < RECURRING_REGULAR_SHARE_PCT * len(gaps):
            continue
        return cadence
    return None


def _build(
    charges: Iterable[DescribedTransaction],
    *,
    channel: str,
    direction: str,
    cadence: Cadence,
    currency: str,
    as_of: date,
) -> Series:
    ordered = tuple(sorted(charges, key=_order))
    prices = [_price(charge, currency) for charge in ordered]
    pairs = list(pairwise(prices))
    equal = sum(1 for a, b in pairs if _same_price(a, b))
    fixed = not pairs or equal * 100 >= FIXED_AMOUNT_SHARE_PCT * len(pairs)

    changes: list[PriceChange] = []
    level = prices[0]
    for index in range(1 if fixed else len(prices), len(prices)):
        price = prices[index]
        if _same_price(level, price):
            continue
        following = prices[index + 1] if index + 1 < len(prices) else None
        if following is not None and not _same_price(price, following):
            continue
        changes.append(
            PriceChange(
                on=ordered[index].posted_on,
                before_minor=level[1],
                after_minor=price[1],
                currency=price[0],
                confirmed=following is not None,
            )
        )
        level = price

    overdue = (
        as_of - ordered[-1].posted_on
    ).days > cadence.max_days + RECURRING_GRACE_DAYS
    return Series(
        channel=channel,
        direction=direction,
        cadence=cadence,
        charges=ordered,
        currency=currency,
        fixed=fixed,
        status="stopped" if overdue else "active",
        changes=tuple(changes),
    )


def _continues(earlier: Series, later: Series) -> bool:
    if (earlier.channel, earlier.direction, earlier.cadence.name) != (
        later.channel,
        later.direction,
        later.cadence.name,
    ):
        return False
    gap = (later.first - earlier.last).days
    if not earlier.cadence.min_days <= gap <= earlier.cadence.max_days:
        return False
    if not _same_price(
        _price(earlier.charges[-1], earlier.currency),
        _price(later.charges[0], later.currency),
    ):
        return False
    a, b = earlier.charges[-1].counterparty_key, later.charges[0].counterparty_key
    common = SequenceMatcher(None, a, b, autojunk=False).find_longest_match(
        0, len(a), 0, len(b)
    )
    return common.size >= RENAME_MIN_COMMON_CHARS


def _link_renamed(found: list[Series], *, currency: str, as_of: date) -> list[Series]:
    series = list(found)
    merged = True
    while merged:
        merged = False
        for earlier in series:
            later = next(
                (s for s in series if s is not earlier and _continues(earlier, s)), None
            )
            if later is None:
                continue
            combined = _build(
                earlier.charges + later.charges,
                channel=earlier.channel,
                direction=earlier.direction,
                cadence=earlier.cadence,
                currency=currency,
                as_of=as_of,
            )
            series = [s for s in series if s is not earlier and s is not later] + [
                combined
            ]
            merged = True
            break
    return series


def detect_series(
    rows: Sequence[DescribedTransaction], *, currency: str, as_of: date | None = None
) -> list[Series]:
    """Find every recurring series in an account's transactions.

    Args:
        rows: Described transactions of one account.
        currency: The account's currency.
        as_of: Date statuses are judged at; defaults to the latest row.

    Returns:
        Active series by monthly equivalent, largest first, then stopped
        series by latest charge, newest first.
    """
    if not rows:
        return []
    as_of = as_of or max(row.posted_on for row in rows)
    candidates = [
        row
        for row in rows
        if row.amount_minor != 0
        and row.channel not in EXCLUDED_CHANNELS
        and (row.amount_minor < 0 or row.channel in INCOMING_CHANNELS)
    ]

    found: list[Series] = []
    for (channel, direction, _key), members in _group(candidates).items():
        frequent = _per_month(members) > HABITUAL_CHARGES_PER_MONTH
        tolerance = (
            RECURRING_VARIABLE_TOLERANCE_PCT
            if channel in WIDE_TOLERANCE_CHANNELS
            else RECURRING_AMOUNT_TOLERANCE_PCT
        )
        for chain in _chain(_without_habits(members, currency), currency, tolerance):
            cadence = _cadence([charge.posted_on for charge in chain])
            if cadence is None:
                continue
            series = _build(
                chain,
                channel=channel,
                direction=direction,
                cadence=cadence,
                currency=currency,
                as_of=as_of,
            )
            if not series.fixed and channel not in VARIABLE_CHANNELS and frequent:
                continue
            if cadence.name == "annual" and (
                not series.fixed or series.current_minor < ANNUAL_MIN_AMOUNT_MINOR
            ):
                continue
            found.append(series)

    series = _link_renamed(found, currency=currency, as_of=as_of)
    active = sorted(
        (s for s in series if s.status == "active"),
        key=lambda s: (-s.monthly_minor, s.name),
    )
    stopped = sorted(
        (s for s in series if s.status == "stopped"),
        key=lambda s: (-s.last.toordinal(), s.name),
    )
    return active + stopped


def build_report(
    rows: Sequence[DescribedTransaction],
    *,
    currency: str,
    as_of: date | None = None,
    window_days: int = RECURRING_REPORT_WINDOW_DAYS,
) -> RecurringReport:
    """Detect series and frame them in a window ending at the latest transaction.

    Raises:
        ValueError: If there are no transactions.
    """
    if not rows:
        raise ValueError(
            "No transactions to look for recurring payments in; import first."
        )
    as_of = as_of or max(row.posted_on for row in rows)
    return RecurringReport(
        as_of=as_of,
        since=as_of - timedelta(days=window_days),
        series=tuple(detect_series(rows, currency=currency, as_of=as_of)),
    )
