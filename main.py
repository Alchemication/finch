"""finch — a personal financial ledger that knows where the money went.

Subcommands:
    profile   Create and list profiles, one per person.
    init      Create a profile's ledger database.
    account   Add and list bank accounts.
    import    Import a bank export into an account.
    recurring Recurring payments, and what changed about them.
    status    Coverage, balance, imports and balance breaks per account.
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

    uv run python main.py import ~/Downloads/Transaction_Export.csv --dry-run
        Check an export and report what importing it would change.

    uv run python main.py import ~/Downloads/Transaction_Export.csv
        Import it. Importing the same or an overlapping file again adds only new rows.

    uv run python main.py recurring
        Subscriptions, bills, transfers and pay that repeat, with price changes.

    uv run python main.py status
        What the ledger covers, and where its running balance does not add up.

    uv run python main.py db schema
        The live schema as SQL.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

# Ensure src/ is importable when running from the project root.
sys.path.insert(0, str(Path(__file__).parent / "src"))

from cmd_import import cmd_import  # noqa: E402
from cmd_recurring import cmd_recurring  # noqa: E402
from commands import cmd_account, cmd_db, cmd_init, cmd_profile, cmd_status  # noqa: E402
from config import BASE_CURRENCY, RECURRING_REPORT_WINDOW_DAYS  # noqa: E402
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
