"""The category and spend commands: name payees, label payments, see where money went."""

from __future__ import annotations

import argparse
import json
import sqlite3
from collections import defaultdict
from datetime import date
from pathlib import Path

from annotate import (
    confirm_proposals,
    decide_payee,
    group_payees,
    label_transactions,
    load_ledger,
)
from categories import CATEGORIES, UNCLASSIFIED, totals, validate_category
from money import format_minor
from profiles import resolve_profile
from store import add_category_rule, load_category_rules, open_existing_db

_CONFIDENCES = ("high", "medium", "low")


def cmd_category(args: argparse.Namespace) -> None:
    """Dispatch the category subcommands.

    Raises:
        FileNotFoundError: If a proposals file or the database is missing.
        ValueError: On an unknown category, key or transaction.
    """
    if args.category_cmd == "list":
        for slug, label in CATEGORIES.items():
            print(f"{slug:20} {label}")
        return
    profile = resolve_profile(args.profile)
    conn = open_existing_db(profile.db)
    try:
        handler = {
            "propose": _propose,
            "review": _review,
            "confirm": _confirm,
            "set": _set,
            "label": _label,
            "unclassified": _unclassified,
        }[args.category_cmd]
        handler(conn, args)
    finally:
        conn.close()


def _propose(conn: sqlite3.Connection, args: argparse.Namespace) -> None:
    """Load proposed rules from a JSON file: ``[{key, category, confidence, note}]``."""
    path = Path(args.file).expanduser()
    if not path.is_file():
        raise FileNotFoundError(f"No file at {path}.")
    proposals = json.loads(path.read_text(encoding="utf-8"))
    rows, _ = load_ledger(conn)
    known = {item.transaction.counterparty_key for item in rows}
    active = {row["counterparty_key"]: row for row in load_category_rules(conn)}
    added = skipped = 0
    with conn:
        for number, proposal in enumerate(proposals, start=1):
            key = proposal["key"]
            category = validate_category(proposal["category"])
            if category is None:
                raise ValueError(
                    f"Proposal {number}: propose a category; leave a payee out "
                    f"to keep it unclassified."
                )
            confidence = proposal.get("confidence")
            if confidence not in _CONFIDENCES:
                raise ValueError(
                    f"Proposal {number}: confidence must be one of "
                    f"{', '.join(_CONFIDENCES)}."
                )
            if key not in known:
                raise ValueError(
                    f"Proposal {number}: no transaction has the counterparty key "
                    f"{key!r}. Keys come from 'category unclassified'."
                )
            current = active.get(key)
            if current is not None and (
                current["source"] == "owner" or current["category"] == category
            ):
                skipped += 1
                continue
            add_category_rule(
                conn,
                counterparty_key=key,
                category=category,
                source="claude",
                status="proposed",
                confidence=confidence,
                note=proposal.get("note"),
            )
            added += 1
    print(
        f"Proposed {added} rules; skipped {skipped} the owner already decided "
        f"or that were unchanged. Review with 'uv run python main.py category review'."
    )


def _review(conn: sqlite3.Connection, args: argparse.Namespace) -> None:
    """Show pending proposals grouped by category, biggest payees first."""
    from rich.console import Console
    from rich.markup import escape
    from rich.table import Table

    rows, currency = load_ledger(conn)
    payees = group_payees(rows)
    pending = [
        row
        for row in load_category_rules(conn)
        if row["status"] == "proposed"
        and (args.category is None or row["category"] == args.category)
    ]
    console = Console()
    if not pending:
        console.print("No proposals waiting for review.")
        return
    grouped: dict[str, list[sqlite3.Row]] = defaultdict(list)
    for row in pending:
        grouped[row["category"]].append(row)
    for slug in CATEGORIES:
        if slug not in grouped:
            continue
        items = sorted(
            grouped[slug], key=lambda r: -payees[r["counterparty_key"]].out_minor
        )
        table = Table(title=f"{CATEGORIES[slug]} ({slug})", title_justify="left")
        table.add_column("Key", style="dim")
        table.add_column("Payee", style="bold")
        table.add_column("Payments", justify="right")
        table.add_column("Out", justify="right")
        table.add_column("In", justify="right")
        table.add_column("Confidence")
        table.add_column("Note")
        for row in items:
            payee = payees[row["counterparty_key"]]
            table.add_row(
                escape(payee.key),
                escape(payee.name),
                str(payee.payments),
                format_minor(payee.out_minor, currency),
                format_minor(payee.in_minor, currency) if payee.in_minor else "",
                row["confidence"] or "",
                escape(row["note"] or ""),
            )
        console.print(table)
    console.print(
        "Confirm with [cyan]uv run python main.py category confirm --category SLUG[/cyan] "
        "(add [cyan]--except KEY[/cyan] to hold some back), or correct one with "
        "[cyan]category set KEY SLUG[/cyan]."
    )


def _confirm(conn: sqlite3.Connection, args: argparse.Namespace) -> None:
    """Turn proposals into owner rules: by category, by key, or all."""
    count = confirm_proposals(
        conn,
        keys=args.keys,
        categories=args.category,
        every=args.all,
        exclude=args.exclude,
    )
    print(f"Confirmed {count} rules.")


def _set(conn: sqlite3.Connection, args: argparse.Namespace) -> None:
    """Record the owner's own rule for a counterparty key."""
    decide_payee(conn, args.key, args.category, args.note)
    slug = validate_category(args.category)
    print(f"{args.key}: {CATEGORIES[slug] if slug else 'unclassified'}.")


def _label(conn: sqlite3.Connection, args: argparse.Namespace) -> None:
    """Record the owner's category for one or more transactions."""
    label_transactions(conn, args.ids, args.category, args.note)
    slug = validate_category(args.category)
    name = CATEGORIES[slug] if slug else "unclassified"
    print(f"{len(args.ids)} transactions: {name}.")


def _unclassified(conn: sqlite3.Connection, args: argparse.Namespace) -> None:
    """List the biggest unclassified payees, and the biggest single payments."""
    from rich.console import Console
    from rich.markup import escape
    from rich.table import Table

    rows, currency = load_ledger(conn)
    loose = [item for item in rows if item.category == UNCLASSIFIED]
    console = Console()
    if not loose:
        console.print("Everything is classified.")
        return
    out_total = sum(
        -i.transaction.amount_minor for i in loose if i.transaction.amount_minor < 0
    )
    console.print(
        f"Unclassified: {len(loose)} transactions, "
        f"{format_minor(out_total, currency)} out."
    )
    payees = sorted(
        group_payees(loose).values(), key=lambda p: -(p.out_minor + p.in_minor)
    )
    table = Table(title="Biggest unclassified payees", title_justify="left")
    table.add_column("Key", style="dim")
    table.add_column("Payee", style="bold")
    table.add_column("Payments", justify="right")
    table.add_column("Out", justify="right")
    table.add_column("In", justify="right")
    for payee in payees[: args.limit]:
        table.add_row(
            escape(payee.key),
            escape(payee.name),
            str(payee.payments),
            format_minor(payee.out_minor, currency) if payee.out_minor else "",
            format_minor(payee.in_minor, currency) if payee.in_minor else "",
        )
    console.print(table)

    singles = sorted(loose, key=lambda i: -abs(i.transaction.amount_minor))
    table = Table(title="Biggest unclassified payments", title_justify="left")
    table.add_column("#", justify="right")
    table.add_column("Date")
    table.add_column("Amount", justify="right")
    table.add_column("How")
    table.add_column("Payee or reference", style="bold")
    for item in singles[: args.limit]:
        tx = item.transaction
        table.add_row(
            str(tx.transaction_id),
            tx.posted_on.isoformat(),
            format_minor(tx.amount_minor, currency),
            tx.channel.replace("_", " "),
            escape(tx.counterparty),
        )
    console.print(table)
    console.print(
        "Name a payee with [cyan]category set KEY SLUG[/cyan], or one payment with "
        "[cyan]category label SLUG N [N ...] --note TEXT[/cyan]."
    )


def cmd_spend(args: argparse.Namespace) -> None:
    """Show money out and in by category, per year or per month.

    Raises:
        ValueError: If the ledger is empty or mixes currencies.
    """
    from rich.console import Console
    from rich.table import Table

    profile = resolve_profile(args.profile)
    conn = open_existing_db(profile.db)
    try:
        rows, currency = load_ledger(conn)
    finally:
        conn.close()

    first = min(item.transaction.posted_on for item in rows)
    last = max(item.transaction.posted_on for item in rows)
    if args.monthly:
        periods = _months(first, last)[-args.months :]
    else:
        periods = [
            (date(year, 1, 1), date(year, 12, 31), str(year))
            for year in range(first.year, last.year + 1)
        ]
    columns = [totals(rows, start=start, end=end) for start, end, _ in periods]
    slugs = [
        slug
        for slug in [*CATEGORIES, UNCLASSIFIED]
        if any(t.category == slug for col in columns for t in col)
    ]

    table = Table(
        title=f"Spending by category, net of refunds ({first} to {last})",
        title_justify="left",
    )
    table.add_column("Category", style="bold")
    for _, _, label in periods:
        table.add_column(label, justify="right")
    for slug in slugs:
        cells = []
        for col in columns:
            found = next((t for t in col if t.category == slug), None)
            cells.append(format_minor(found.net_out_minor, currency) if found else "")
        label = CATEGORIES.get(slug, "Unclassified")
        table.add_row(
            f"[yellow]{label}[/yellow]" if slug == UNCLASSIFIED else label, *cells
        )
    out_row = [format_minor(sum(t.out_minor for t in col), currency) for col in columns]
    in_row = [format_minor(sum(t.in_minor for t in col), currency) for col in columns]
    table.add_section()
    table.add_row("All money out", *out_row)
    table.add_row("All money in", *in_row)
    console = Console()
    console.print(table)
    console.print(
        "Negative figures mean more came in than went out. A partial first or last "
        "period covers only the dates the ledger holds."
    )


def _months(first: date, last: date) -> list[tuple[date, date, str]]:
    periods = []
    year, month = first.year, first.month
    while (year, month) <= (last.year, last.month):
        nxt = date(year + month // 12, month % 12 + 1, 1)
        end = date.fromordinal(nxt.toordinal() - 1)
        periods.append((date(year, month, 1), end, f"{year}-{month:02d}"))
        year, month = nxt.year, nxt.month
    return periods
