"""The doc command: keep contracts, letters and agreements beside the statements."""

from __future__ import annotations

import argparse
import subprocess
import sys
from datetime import date
from pathlib import Path

from models import Document
from profiles import resolve_profile
from sources import archive_source, archived_file
from store import (
    add_document,
    find_document,
    get_document,
    load_documents,
    load_imports,
    open_existing_db,
)


def cmd_doc(args: argparse.Namespace) -> None:
    """Add a document, list everything kept, or open one document.

    Raises:
        FileNotFoundError: If the file, the profile's database or an archived
            file is missing.
        ValueError: If the date is malformed or the document id is unknown.
    """
    if args.doc_cmd == "add":
        _add(args)
    elif args.doc_cmd == "list":
        _list(args)
    else:
        _open(args)


def _parse_date(text: str | None) -> date | None:
    if text is None:
        return None
    try:
        return date.fromisoformat(text)
    except ValueError:
        raise ValueError(
            f"--date must be YYYY-MM-DD, e.g. 2026-08-12, not {text!r}."
        ) from None


def _add(args: argparse.Namespace) -> None:
    from rich.console import Console
    from rich.markup import escape

    console = Console()
    profile = resolve_profile(args.profile)
    path = Path(args.file).expanduser()
    if not path.is_file():
        raise FileNotFoundError(f"No file at {path}.")
    dated_on = _parse_date(args.date)
    content = path.read_bytes()

    conn = open_existing_db(profile.db)
    try:
        digest, _ = archive_source(profile.sources, content, suffix=path.suffix)
        existing = find_document(conn, digest)
        if existing is not None:
            console.print(
                f"Already kept as #{existing.id}: {escape(existing.title)}. "
                f"Nothing changed."
            )
            return
        with conn:
            document = add_document(
                conn,
                Document(
                    sha256=digest,
                    original_name=path.name,
                    title=args.title,
                    dated_on=dated_on,
                    note=args.note,
                ),
            )
    finally:
        conn.close()
    console.print(f"[green]Kept[/green] #{document.id}: {escape(document.title)}")
    console.print(
        f"The original at {escape(str(path))} can be deleted; "
        f"open the kept copy with [cyan]uv run python main.py doc open "
        f"{document.id}[/cyan]."
    )


def _list(args: argparse.Namespace) -> None:
    from rich.console import Console
    from rich.markup import escape
    from rich.table import Table

    console = Console()
    profile = resolve_profile(args.profile)
    conn = open_existing_db(profile.db)
    try:
        documents = load_documents(conn)
        imports = load_imports(conn)
    finally:
        conn.close()

    if not documents and not imports:
        console.print(
            "Nothing kept yet. Add a document with "
            "[cyan]uv run python main.py doc add FILE --title TITLE[/cyan]."
        )
        return

    if documents:
        table = Table(title="Documents")
        table.add_column("#", justify="right")
        table.add_column("Dated")
        table.add_column("Title", style="bold")
        table.add_column("Note")
        table.add_column("Added from", style="dim", overflow="fold")
        for document in documents:
            table.add_row(
                str(document.id),
                document.dated_on.isoformat() if document.dated_on else "—",
                escape(document.title),
                escape(document.note or ""),
                escape(document.original_name),
            )
        console.print(table)
        console.print("Open one with [cyan]uv run python main.py doc open N[/cyan].")

    if imports:
        table = Table(title="Statements")
        table.add_column("Account", style="bold")
        table.add_column("Covers")
        table.add_column("Rows", justify="right")
        table.add_column("Archived at", style="dim", overflow="fold")
        for row in imports:
            kept = archived_file(profile.sources, row["source_sha256"])
            covers = (
                f"{row['first_posted_on']} to {row['last_posted_on']}"
                if row["first_posted_on"]
                else "no rows"
            )
            table.add_row(
                escape(row["account"]),
                covers,
                str(row["rows_seen"]),
                escape(str(kept)) if kept else "missing from the archive",
            )
        console.print(table)


def _open(args: argparse.Namespace) -> None:
    profile = resolve_profile(args.profile)
    conn = open_existing_db(profile.db)
    try:
        document = get_document(conn, args.id)
    finally:
        conn.close()
    kept = archived_file(profile.sources, document.sha256)
    if kept is None:
        raise FileNotFoundError(
            f"Document #{document.id} is recorded but its file is missing from "
            f"{profile.sources / document.sha256}. Add it again with 'doc add'."
        )
    print(kept)
    opener = "open" if sys.platform == "darwin" else "xdg-open"
    subprocess.run([opener, str(kept)], check=False)
