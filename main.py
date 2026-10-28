"""finch — a personal financial ledger that knows where the money went.

Subcommands:
    profile   Create and list profiles, one per person.
    init      Create a profile's ledger database.
    account   Add and list bank accounts, and keep their IBAN and BIC.
    import    Import a bank export into an account.
    recurring Recurring payments, and what changed about them.
    status    Coverage, balance, imports and balance breaks per account.
    doc       Keep contracts, letters and agreements beside the statements.
    category  Name payees and payments with categories; review proposals.
    spend     Money out and in by category, per year or month.
    ui        A local page for naming payees and seeing where money went.
    db        Migration state, row counts and the live schema.

Every ledger command is profile-scoped. --profile NAME selects one; omitting it
means the operator profile from profiles.toml.

Examples:
    uv run python main.py profile add me --operator
        Create the first profile and its private directory.

    uv run python main.py init
        Create the operator profile's ledger database.

    uv run python main.py account add aib-current --institution AIB --kind current --last4 1234
        Register an account exports will be imported into.

    uv run python main.py account details aib-current --iban "IE29 AIBK ..." --bic AIBKIE2D
        Keep the account's IBAN and BIC; without --iban, print them.

    uv run python main.py import ~/Downloads/Transaction_Export.csv --dry-run
        Check an export and report what importing it would change.

    uv run python main.py import ~/Downloads/Transaction_Export.csv
        Import it. Importing the same or an overlapping file again adds only new rows.

    uv run python main.py recurring
        Subscriptions, bills, transfers and pay that repeat, with price changes.

    uv run python main.py status
        What the ledger covers, and where its running balance does not add up.

    uv run python main.py doc add ~/Downloads/agreement.pdf --title "Car finance agreement" --date 2025-04-01
        Keep a document in the private archive, with a title to find it by.

    uv run python main.py doc list
        Every kept document and statement, and where its file is.

    uv run python main.py category unclassified
        The biggest payees and payments nothing has named yet.

    uv run python main.py spend --monthly
        Spending by category for the last twelve months.

    uv run python main.py ui
        Open the annotation page in the browser (local only).

    uv run python main.py db schema
        The live schema as SQL.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

# Ensure src/ is importable when running from the project root.
sys.path.insert(0, str(Path(__file__).parent / "src"))

from cmd_categories import cmd_category, cmd_spend  # noqa: E402
from cmd_documents import cmd_doc  # noqa: E402
from cmd_import import cmd_import  # noqa: E402
from cmd_ui import cmd_ui  # noqa: E402
from cmd_recurring import cmd_recurring  # noqa: E402
from commands import cmd_account, cmd_db, cmd_init, cmd_profile, cmd_status  # noqa: E402
from config import (  # noqa: E402
    BASE_CURRENCY,
    RECURRING_REPORT_WINDOW_DAYS,
    SPEND_MONTHS_SHOWN,
    UI_PORT,
    UNCLASSIFIED_SHOWN,
)
from log import setup_logging  # noqa: E402
from models import ACCOUNT_KINDS  # noqa: E402


def build_parser() -> argparse.ArgumentParser:
    """Build the full argument parser.

    Separate from :func:`main` so tests can walk the command tree.

    Returns:
        The configured parser.
    """
    parser = argparse.ArgumentParser(
        description="A personal financial ledger",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    parser.add_argument(
        "--verbose", action="store_true", help="Debug logging on stderr"
    )
    sub = parser.add_subparsers(dest="cmd", required=True)

    def _add_profile_flag(subparser: argparse.ArgumentParser) -> None:
        subparser.add_argument(
            "--profile",
            metavar="NAME",
            default=None,
            help="Profile name (default: the operator profile)",
        )

    p_profile = sub.add_parser("profile", help="Create and list profiles")
    profile_sub = p_profile.add_subparsers(dest="profile_cmd", required=True)
    p_profile_add = profile_sub.add_parser("add", help="Create a profile")
    p_profile_add.add_argument("name", help="Profile name (lowercase, no spaces)")
    p_profile_add.add_argument(
        "--operator",
        action="store_true",
        help="Make this the default profile for commands without --profile",
    )
    profile_sub.add_parser("list", help="List the roster")
    p_profile.set_defaults(func=cmd_profile)

    p_init = sub.add_parser("init", help="Create a profile's ledger database")
    _add_profile_flag(p_init)
    p_init.set_defaults(func=cmd_init)

    p_account = sub.add_parser("account", help="Add and list bank accounts")
    account_sub = p_account.add_subparsers(dest="account_cmd", required=True)
    p_account_add = account_sub.add_parser("add", help="Register an account")
    p_account_add.add_argument("name", help="Short handle, e.g. aib-current")
    p_account_add.add_argument("--institution", required=True, help="Bank name")
    p_account_add.add_argument("--kind", required=True, choices=ACCOUNT_KINDS)
    p_account_add.add_argument(
        "--currency", default=BASE_CURRENCY, help=f"ISO code (default: {BASE_CURRENCY})"
    )
    p_account_add.add_argument(
        "--last4",
        default=None,
        metavar="DIGITS",
        help="Last four digits of the account number; imports are checked against it",
    )
    _add_profile_flag(p_account_add)
    p_account_list = account_sub.add_parser("list", help="List accounts")
    _add_profile_flag(p_account_list)
    p_account_details = account_sub.add_parser(
        "details", help="Show an account's IBAN, BIC and sort code, or enter them"
    )
    p_account_details.add_argument("name", help="Account name, e.g. aib-current")
    p_account_details.add_argument(
        "--iban", default=None, help="Store this IBAN (checked by its check digits)"
    )
    p_account_details.add_argument("--bic", default=None, help="Store this BIC")
    _add_profile_flag(p_account_details)
    p_account.set_defaults(func=cmd_account)

    p_import = sub.add_parser("import", help="Import a bank export into an account")
    p_import.add_argument("file", help="The exported file, e.g. AIB's transaction CSV")
    p_import.add_argument(
        "--account",
        metavar="NAME",
        default=None,
        help="Account to import into (default: the profile's only account)",
    )
    p_import.add_argument(
        "--dry-run",
        action="store_true",
        help="Check the file and report what would change, writing nothing",
    )
    _add_profile_flag(p_import)
    p_import.set_defaults(func=cmd_import)

    p_recurring = sub.add_parser(
        "recurring", help="Recurring payments and what changed"
    )
    p_recurring.add_argument(
        "--account",
        metavar="NAME",
        default=None,
        help="Account to look at (default: the profile's only account)",
    )
    p_recurring.add_argument(
        "--window-days",
        type=int,
        default=RECURRING_REPORT_WINDOW_DAYS,
        metavar="N",
        help=f"How far back to look for changes (default: {RECURRING_REPORT_WINDOW_DAYS})",
    )
    p_recurring.add_argument(
        "--all", action="store_true", help="Also list stopped payments"
    )
    _add_profile_flag(p_recurring)
    p_recurring.set_defaults(func=cmd_recurring)

    p_status = sub.add_parser("status", help="Ledger coverage and balance breaks")
    _add_profile_flag(p_status)
    p_status.set_defaults(func=cmd_status)

    p_doc = sub.add_parser(
        "doc", help="Keep and find contracts, letters and agreements"
    )
    doc_sub = p_doc.add_subparsers(dest="doc_cmd", required=True)
    p_doc_add = doc_sub.add_parser("add", help="Keep a document in the archive")
    p_doc_add.add_argument("file", help="The document, e.g. a PDF")
    p_doc_add.add_argument("--title", required=True, help="What to call it")
    p_doc_add.add_argument(
        "--date", default=None, metavar="YYYY-MM-DD", help="The date it carries"
    )
    p_doc_add.add_argument("--note", default=None, help="Anything worth remembering")
    _add_profile_flag(p_doc_add)
    p_doc_list = doc_sub.add_parser("list", help="Kept documents and statements")
    _add_profile_flag(p_doc_list)
    p_doc_open = doc_sub.add_parser("open", help="Open a kept document")
    p_doc_open.add_argument("id", type=int, help="Document number from 'doc list'")
    _add_profile_flag(p_doc_open)
    p_doc.set_defaults(func=cmd_doc)

    p_cat = sub.add_parser("category", help="Name payees and payments with categories")
    cat_sub = p_cat.add_subparsers(dest="category_cmd", required=True)
    cat_sub.add_parser("list", help="The categories and their slugs")
    p_cat_propose = cat_sub.add_parser("propose", help="Load proposed rules from JSON")
    p_cat_propose.add_argument(
        "file", help="JSON list of {key, category, confidence, note}"
    )
    _add_profile_flag(p_cat_propose)
    p_cat_review = cat_sub.add_parser("review", help="Proposals waiting for review")
    p_cat_review.add_argument("--category", default=None, metavar="SLUG")
    _add_profile_flag(p_cat_review)
    p_cat_confirm = cat_sub.add_parser("confirm", help="Confirm proposals")
    p_cat_confirm.add_argument(
        "--category", action="append", metavar="SLUG", help="Every proposal in it"
    )
    p_cat_confirm.add_argument(
        "--key", dest="keys", action="append", metavar="KEY", help="One payee"
    )
    p_cat_confirm.add_argument(
        "--except", dest="exclude", action="append", metavar="KEY", help="Hold back"
    )
    p_cat_confirm.add_argument("--all", action="store_true", help="Every proposal")
    _add_profile_flag(p_cat_confirm)
    p_cat_set = cat_sub.add_parser("set", help="Name a payee yourself")
    p_cat_set.add_argument("key", help="Counterparty key, as listed")
    p_cat_set.add_argument("category", help="Category slug, or 'none'")
    p_cat_set.add_argument("--note", default=None)
    _add_profile_flag(p_cat_set)
    p_cat_label = cat_sub.add_parser("label", help="Name one or more payments")
    p_cat_label.add_argument("category", help="Category slug, or 'none'")
    p_cat_label.add_argument(
        "ids", type=int, nargs="+", metavar="ID", help="Transaction numbers, as listed"
    )
    p_cat_label.add_argument("--note", default=None, help="What it was")
    _add_profile_flag(p_cat_label)
    p_cat_loose = cat_sub.add_parser(
        "unclassified", help="Biggest payees and payments with no category"
    )
    p_cat_loose.add_argument(
        "--limit",
        type=int,
        default=UNCLASSIFIED_SHOWN,
        metavar="N",
        help=f"How many of each to list (default: {UNCLASSIFIED_SHOWN})",
    )
    _add_profile_flag(p_cat_loose)
    p_cat.set_defaults(func=cmd_category)

    p_spend = sub.add_parser("spend", help="Money out and in by category")
    p_spend.add_argument("--monthly", action="store_true", help="Per month, not year")
    p_spend.add_argument(
        "--months",
        type=int,
        default=SPEND_MONTHS_SHOWN,
        metavar="N",
        help=f"Months shown with --monthly (default: {SPEND_MONTHS_SHOWN})",
    )
    _add_profile_flag(p_spend)
    p_spend.set_defaults(func=cmd_spend)

    p_ui = sub.add_parser("ui", help="Local page for naming payees and insights")
    p_ui.add_argument(
        "--port",
        type=int,
        default=UI_PORT,
        help="Port on 127.0.0.1 (default: a free one)",
    )
    p_ui.add_argument("--no-open", action="store_true", help="Do not open the browser")
    _add_profile_flag(p_ui)
    p_ui.set_defaults(func=cmd_ui)

    p_db = sub.add_parser("db", help="Migration state and schema")
    db_sub = p_db.add_subparsers(dest="db_cmd", required=True)
    for name, text in (
        ("status", "Migrations and row counts"),
        ("schema", "Live schema"),
    ):
        _add_profile_flag(db_sub.add_parser(name, help=text))
    p_db.set_defaults(func=cmd_db)

    return parser


def main(argv: list[str] | None = None) -> int:
    """Parse arguments, run one command, and return an exit code."""
    args = build_parser().parse_args(argv)
    setup_logging(args.verbose)
    try:
        args.func(args)
    except (FileNotFoundError, ValueError) as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
