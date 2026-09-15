"""CLI handlers. Rendering only; the work happens in the modules they call."""

from __future__ import annotations

import argparse
import sqlite3

from config import BALANCE_BREAKS_SHOWN
from db.migrations import get_live_schema, list_migrations
from ledger import balance_breaks, latest_balance
from models import Account
from money import format_minor
from profiles import add_profile, load_profiles, resolve_profile
from store import (
    account_summary,
    add_account,
    get_account,
    load_accounts,
    open_db,
    open_existing_db,
    table_counts,
)


def cmd_profile(args: argparse.Namespace) -> None:
    """Create a profile or list the roster."""
    from rich.console import Console
    from rich.table import Table

    console = Console()
    if args.profile_cmd == "add":
        profile = add_profile(args.name, operator=args.operator)
        console.print(
            f"[green]Created profile[/green] {profile.name} at {profile.root}"
        )
        console.print(
            f"Next: [cyan]uv run python main.py init --profile {profile.name}[/cyan]"
        )
        return

    table = Table(title="Profiles")
    table.add_column("Name", style="bold")
    table.add_column("Default", justify="center")
    table.add_column("Enabled", justify="center")
    table.add_column("Database", style="dim", overflow="fold")
    for profile in sorted(load_profiles().values(), key=lambda item: item.name):
        table.add_row(
            profile.name,
            "yes" if profile.operator else "",
            "yes" if profile.enabled else "no",
            str(profile.db) if profile.db.exists() else "not initialised",
        )
    console.print(table)


def cmd_init(args: argparse.Namespace) -> None:
    """Create a profile's ledger database, or migrate an existing one."""
    from rich.console import Console

    console = Console()
    profile = resolve_profile(args.profile, require_db=False)
    existed = profile.db.exists()
    conn = open_db(profile.db)
    conn.close()
    if existed:
        console.print(f"Database already exists at {profile.db}; schema is up to date.")
        return
    console.print(f"[green]Created ledger[/green] at {profile.db}")
    console.print(
        "Next: [cyan]uv run python main.py account add NAME --institution BANK "
        "--kind current[/cyan]"
    )


def cmd_account(args: argparse.Namespace) -> None:
    """Add an account or list accounts."""
    from rich.console import Console
    from rich.table import Table

    console = Console()
    profile = resolve_profile(args.profile)
    conn = open_existing_db(profile.db)
    try:
        if args.account_cmd == "add":
            account = Account(
                name=args.name,
                institution=args.institution,
                kind=args.kind,
                currency=args.currency,
                identifier_hint=args.last4,
            )
            with conn:
                stored = add_account(conn, account)
            console.print(
                f"[green]Added account[/green] {stored.name} ({stored.institution})"
            )
            return

        table = Table(title=f"Accounts — {profile.name}")
        table.add_column("Name", style="bold")
        table.add_column("Institution")
        table.add_column("Kind")
        table.add_column("Currency")
        table.add_column("Ends in")
        for account in load_accounts(conn):
            table.add_row(
                account.name,
                account.institution,
                account.kind,
                account.currency,
                account.identifier_hint or "",
            )
        console.print(table)
    finally:
        conn.close()


def cmd_status(args: argparse.Namespace) -> None:
    """Show each account's coverage, balance, imports and balance breaks."""
    from rich.console import Console
    from rich.table import Table

    console = Console()
    profile = resolve_profile(args.profile)
    conn = open_existing_db(profile.db)
    try:
        accounts = load_accounts(conn)
        if not accounts:
            console.print(
                f"Profile {profile.name} has no accounts. Add one with "
                f"[cyan]uv run python main.py account add[/cyan]."
            )
            return

        table = Table(title=f"Ledger — {profile.name}")
        table.add_column("Account", style="bold")
        table.add_column("Transactions", justify="right")
        table.add_column("From")
        table.add_column("To")
        table.add_column("Balance", justify="right")
        table.add_column("Imports", justify="right")
        table.add_column("Breaks", justify="right")
        all_breaks = {}
        for account in accounts:
            summary = account_summary(conn, account.id)
            balance = latest_balance(conn, account.id)
            breaks = balance_breaks(conn, account.id)
            all_breaks[account.name] = (account, breaks)
            table.add_row(
                account.name,
                str(summary["transactions"]),
                summary["first_posted_on"] or "—",
                summary["last_posted_on"] or "—",
                format_minor(balance[1], account.currency) if balance else "unknown",
                str(summary["imports"]),
                f"[red]{len(breaks)}[/red]" if breaks else "0",
            )
        console.print(table)

        for name, (account, breaks) in all_breaks.items():
            if not breaks:
                continue
            console.print(
                f"\n[red]{name}: {len(breaks)} balance break(s).[/red] Rows are "
                f"missing between statements, or an overlapping statement "
                f"disagreed with an earlier one."
            )
            for found in breaks[:BALANCE_BREAKS_SHOWN]:
                console.print(
                    f"  {found.day}: expected "
                    f"{format_minor(found.expected_minor, account.currency)}, "
                    f"statement printed {format_minor(found.found_minor, account.currency)}"
                )
    finally:
        conn.close()


def cmd_db(args: argparse.Namespace) -> None:
    """Show migration state and row counts, or print the live schema."""
    from rich.console import Console
    from rich.table import Table

    console = Console()
    profile = resolve_profile(args.profile)
    conn = open_existing_db(profile.db)
    try:
        if args.db_cmd == "schema":
            print(get_live_schema(conn))
            return

        migrations = Table(title=f"Migrations — {profile.db}")
        migrations.add_column("Status")
        migrations.add_column("Key", overflow="fold")
        migrations.add_column("Applied")
        for status in list_migrations(conn):
            migrations.add_row(status.status, status.key, status.applied_at or "")
        console.print(migrations)

        counts = Table(title="Rows")
        counts.add_column("Table")
        counts.add_column("Rows", justify="right")
        for table, count in table_counts(conn).items():
            counts.add_row(table, str(count))
        console.print(counts)
    finally:
        conn.close()


def choose_account(conn: sqlite3.Connection, name: str | None) -> Account:
    """Return the named account, or the only one when none is named.

    Raises:
        ValueError: If no account exists, or several do and none was named.
    """
    if name:
        return get_account(conn, name)
    accounts = load_accounts(conn)
    if len(accounts) == 1:
        return accounts[0]
    if not accounts:
        raise ValueError(
            "This profile has no accounts. Add one first with 'uv run python main.py "
            "account add NAME --institution BANK --kind current --last4 DIGITS'."
        )
    names = ", ".join(account.name for account in accounts)
    raise ValueError(
        f"This profile has several accounts; choose one with --account ({names})."
    )
