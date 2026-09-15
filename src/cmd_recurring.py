"""The recurring command: regular payments, and what changed about them."""

from __future__ import annotations

import argparse

from commands import choose_account
from describe import describe_account
from money import format_minor
from profiles import resolve_profile
from recurring import RecurringReport, Series, build_report
from store import open_existing_db

CHANNEL_LABELS: dict[str, str] = {
    "card": "card",
    "atm": "cash",
    "direct_debit": "direct debit",
    "transfer_out": "transfer sent",
    "transfer_in": "transfer received",
    "fee": "bank fee",
    "other": "other",
}


def _how(series: Series) -> str:
    label = CHANNEL_LABELS.get(series.channel, series.channel)
    return label if series.fixed else f"{label}, varies"


def _price(series: Series) -> str:
    return format_minor(series.current_price_minor, series.price_currency)


def _signed(minor: int, currency: str) -> str:
    return ("+" if minor > 0 else "") + format_minor(minor, currency)


def cmd_recurring(args: argparse.Namespace) -> None:
    """Show recurring payments and what changed, started and stopped recently.

    Raises:
        ValueError: If the account is ambiguous or has no transactions.
    """
    from rich.console import Console

    profile = resolve_profile(args.profile)
    conn = open_existing_db(profile.db)
    try:
        account = choose_account(conn, args.account)
        rows = describe_account(conn, account.id)
    finally:
        conn.close()
    if not rows:
        raise ValueError(
            f"Account {account.name} has no transactions. Import an export first with "
            f"'uv run python main.py import FILE'."
        )
    report = build_report(rows, currency=account.currency, window_days=args.window_days)
    _render(Console(), report, account.name, account.currency, show_all=args.all)


def _render(
    console: object,
    report: RecurringReport,
    account_name: str,
    currency: str,
    *,
    show_all: bool,
) -> None:
    from rich.markup import escape
    from rich.table import Table

    console.print(
        f"[bold]Recurring payments in {escape(account_name)}[/bold] as of {report.as_of}, "
        f"the ledger's latest transaction."
    )
    if not report.series:
        console.print(
            "No recurring payments found yet. A monthly payment needs three charges to count."
        )
        return

    out = [s for s in report.active if s.direction == "out"]
    incoming = [s for s in report.active if s.direction == "in"]
    console.print(
        f"Going out: {format_minor(report.monthly_minor('out'), currency)} a month "
        f"across {len(out)} payments."
    )
    if incoming:
        console.print(
            f"Coming in: {format_minor(report.monthly_minor('in'), currency)} a month "
            f"across {len(incoming)}."
        )

    console.print(f"\n[bold]Price changes since {report.since}[/bold]")
    changed = report.changed()
    if not changed:
        console.print("  None.")
    for series, change in changed:
        line = (
            f"  {change.on}  {escape(series.name)}: "
            f"{format_minor(change.before_minor, change.currency)} → "
            f"{format_minor(change.after_minor, change.currency)}"
        )
        if change.currency == currency:
            yearly = (
                (change.after_minor - change.before_minor) * 12 // series.cadence.months
            )
            line += f", {_signed(yearly, currency)} a year"
        if not change.confirmed:
            line += " [dim](one charge at the new price so far)[/dim]"
        console.print(line)

    console.print(f"\n[bold]Started since {report.since}[/bold]")
    started = report.started()
    if not started:
        console.print("  None.")
    for series in started:
        console.print(
            f"  {escape(series.name)}: {series.cadence.name}, {_price(series)}, "
            f"first on {series.first}"
        )

    console.print(f"\n[bold]Stopped since {report.since}[/bold]")
    stopped = report.stopped_recently()
    if not stopped:
        console.print("  None.")
    for series in stopped:
        console.print(
            f"  {escape(series.name)}: last {_price(series)} on {series.last}"
        )

    table = Table(title="Active")
    for column, justify in (
        ("Payment", "left"),
        ("How", "left"),
        ("Cadence", "left"),
        ("Price", "right"),
        ("Per month", "right"),
        ("Since", "left"),
        ("Charges", "right"),
    ):
        table.add_column(column, justify=justify)
    for series in out + incoming:
        table.add_row(
            escape(series.name) + (" (in)" if series.direction == "in" else ""),
            _how(series),
            series.cadence.name,
            _price(series),
            format_minor(series.monthly_minor, currency),
            str(series.first),
            str(len(series.charges)),
        )
    console.print()
    console.print(table)

    if not report.stopped:
        return
    if not show_all:
        console.print(
            f"{len(report.stopped)} stopped payments not shown; --all lists them."
        )
        return
    stopped_table = Table(title="Stopped")
    for column in ("Payment", "How", "Cadence", "Last price", "From", "To", "Charges"):
        stopped_table.add_column(column)
    for series in report.stopped:
        stopped_table.add_row(
            escape(series.name),
            _how(series),
            series.cadence.name,
            _price(series),
            str(series.first),
            str(series.last),
            str(len(series.charges)),
        )
    console.print(stopped_table)
