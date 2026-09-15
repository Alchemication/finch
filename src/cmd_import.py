"""The import command: read a bank export, check it, and write it to the ledger."""

from __future__ import annotations

import argparse
from pathlib import Path

from commands import choose_account
from ingest import ImportRejected, import_statement, preview_import
from ledger import latest_balance
from money import format_minor
from parsers import detect
from profiles import resolve_profile
from store import open_existing_db


def cmd_import(args: argparse.Namespace) -> None:
    """Import one bank export, or with --dry-run report what it would do.

    Raises:
        FileNotFoundError: If the file or the profile's database is missing.
        ValueError: If the format is unrecognised or the statement is rejected.
    """
    from rich.console import Console
    from rich.markup import escape

    console = Console()
    profile = resolve_profile(args.profile)
    path = Path(args.file).expanduser()
    if not path.is_file():
        raise FileNotFoundError(f"No file at {path}.")
    content = path.read_bytes()
    parser = detect(content)
    statement = parser.parse(content)

    conn = open_existing_db(profile.db)
    try:
        account = choose_account(conn, args.account)
        rows = statement.rows
        span = f", {rows[0].posted_on} to {rows[-1].posted_on}" if rows else ""
        console.print(
            f"{escape(path.name)}: {len(rows)} rows read as {statement.parser} "
            f"v{statement.parser_version}{span}."
        )
        if statement.account_hint and not account.identifier_hint:
            console.print(
                f"The file is for an account ending {statement.account_hint}; "
                f"{account.name} has no --last4 to check it against."
            )

        if args.dry_run:
            preview = preview_import(
                conn, account=account, statement=statement, content=content
            )
            if preview.problems:
                raise ImportRejected(list(preview.problems))
            if preview.already_imported:
                console.print(
                    "This file was already imported; importing it again changes nothing."
                )
            else:
                console.print(
                    f"Would add {preview.rows_new} new rows to {account.name}; "
                    f"{preview.rows_seen - preview.rows_new} are already in the ledger."
                )
            console.print("Dry run: nothing written.")
            return

        result = import_statement(
            conn,
            account=account,
            statement=statement,
            content=content,
            source_name=path.name,
            archive_root=profile.sources,
        )
        if result.already_imported:
            console.print("This file was already imported; nothing changed.")
            return
        console.print(
            f"[green]Added {result.rows_new} new rows[/green] to {account.name}; "
            f"{result.rows_seen - result.rows_new} were already in the ledger."
        )
        balance = latest_balance(conn, account.id)
        if balance:
            console.print(
                f"Balance after {balance[0]}: {format_minor(balance[1], account.currency)}"
            )
        for found in result.new_breaks:
            console.print(
                f"[red]Balance break on {found.day}[/red]: expected "
                f"{format_minor(found.expected_minor, account.currency)}, statement printed "
                f"{format_minor(found.found_minor, account.currency)}. Rows are missing "
                f"before this date, or an earlier file disagrees with this one."
            )
    finally:
        conn.close()
