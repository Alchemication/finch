"""Paths, permissions, currency and display limits.

Every operational tunable lives here, each with a docstring saying why it has
the value it has. Nothing is inlined at its point of use.

Most values accept a ``FINCH_*`` environment override, read once at import.

Example:
    from config import APP_HOME, BASE_CURRENCY
"""

from __future__ import annotations

import os
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()


# ---------------------------------------------------------------------------
# Paths and permissions
# ---------------------------------------------------------------------------

APP_HOME: Path = Path(
    os.environ.get("FINCH_HOME", "~/Library/Application Support/finch")
).expanduser()
"""Root directory for profiles, ledger databases and archived statements.

Not ``~/Documents``, unlike the sibling projects. On a Mac with iCloud
"Desktop & Documents" enabled, Documents is synced, which uploads every bank
statement to a third party and can corrupt a SQLite database synced while it
is open. Application Support is local and covered by FileVault.
"""

REPOSITORY_ROOT: Path = Path(__file__).resolve().parents[1]
"""The checkout. Private data is refused anywhere beneath it, because git
history is permanent and one stray ``git add -A`` would publish a statement."""

PRIVATE_DIR_MODE: int = 0o700
"""Owner-only directories. Everything under APP_HOME is bank data or derived
from it, and SQLite's ``-wal`` and ``-shm`` files are created with the process
umask, so the directory is what actually protects them."""

PRIVATE_FILE_MODE: int = 0o600
"""Owner-only files: the roster, databases and archived statements."""


# ---------------------------------------------------------------------------
# Currency
# ---------------------------------------------------------------------------

BASE_CURRENCY: str = "EUR"
"""Default currency for a new account. Every account keeps its own currency
column; this is only what ``account add`` assumes when none is given."""


# ---------------------------------------------------------------------------
# Display limits
# ---------------------------------------------------------------------------

IMPORT_PROBLEMS_SHOWN: int = int(os.environ.get("FINCH_IMPORT_PROBLEMS_SHOWN", "10"))
"""Reconciliation problems listed when an import is rejected.

A parser that misreads a layout usually breaks every running balance after the
first bad row, so the first ten say everything the next four hundred would.
"""

BALANCE_BREAKS_SHOWN: int = int(os.environ.get("FINCH_BALANCE_BREAKS_SHOWN", "5"))
"""Ledger balance breaks listed per account by ``status``. Each break usually
marks one missing statement, so a handful locates the gaps; the count is always
shown in full."""

UNCLASSIFIED_SHOWN: int = int(os.environ.get("FINCH_UNCLASSIFIED_SHOWN", "25"))
"""Payees and payments listed by ``category unclassified``. Twenty-five payees
by money moved covered most of a 24-month ledger's unclassified spending, and
a list longer than a screen stops being read."""

SPEND_MONTHS_SHOWN: int = int(os.environ.get("FINCH_SPEND_MONTHS", "12"))
"""Months shown by ``spend --monthly``: a year, so each month sits beside the
same month's neighbours and seasonal costs show up."""


# ---------------------------------------------------------------------------
# Recurring payments
# ---------------------------------------------------------------------------

MONTHLY_GAP_DAYS: tuple[int, int] = (20, 40)
"""Days between two charges of a monthly payment.

Wider than a calendar month on purpose. Card subscriptions post within a few
days of the same date, but hand-typed transfers drift: a real monthly transfer
arrived up to three weeks early or eight days late. A gap of up to
twice this range counts as one missed month.
"""

QUARTERLY_GAP_DAYS: tuple[int, int] = (75, 105)
"""Days between charges of a quarterly payment. AIB's quarterly fee posted
91 to 94 days apart, on a working day near the end of each quarter."""

ANNUAL_GAP_DAYS: tuple[int, int] = (330, 400)
"""Days between charges of an annual payment. A real yearly licence renewal came
almost a month later in the year than the previous one."""

RECURRING_MIN_CHARGES: int = 3
"""Charges before a monthly or quarterly payment counts as recurring. Two
charges a month apart happen by coincidence: two haircuts, two parking fees."""

ANNUAL_MIN_CHARGES: int = 2
"""Charges before an annual payment counts. Three would need three years of
history, which a 24-month export cannot give."""

ANNUAL_MIN_AMOUNT_MINOR: int = 2000
"""Smallest annual payment reported, in minor units. Below €20, two identical
small purchases a year apart are likelier than a yearly bill."""

RECURRING_ON_TIME_SHARE_PCT: int = 50
"""Share of gaps that must fall inside the cadence's range rather than near a
multiple of it. Stops a haircut every six to ten weeks reading as monthly."""

RECURRING_REGULAR_SHARE_PCT: int = 80
"""Share of gaps that must be on time or one missed period. Leaves room for a
skipped month or a salary paid early before a holiday."""

RECURRING_MIN_GAP_DAYS: int = 20
"""A series never charges twice within this many days. This is what separates
several subscriptions billed by one app store into separate series."""

RECURRING_AMOUNT_TOLERANCE_PCT: int = 20
"""Largest step between consecutive charges of one card payment or sent
transfer. A real loan repayment rose by over a tenth in one step; the band keeps
it one
series while separating two subscriptions from one merchant priced far apart."""

RECURRING_VARIABLE_TOLERANCE_PCT: int = 50
"""The same for direct debits, bank fees and incoming transfers, whose amounts
move legitimately: a bank's quarterly fee varied by nearly a third."""

PRICE_CHANGE_MIN_PCT: int = 1
"""Smallest difference reported as a price change; below it amounts count as
equal. Salary credits a cent apart are not a pay change."""

FIXED_AMOUNT_SHARE_PCT: int = 60
"""Share of consecutive charges that must be equal for a payment to count as
fixed-price. Variable card payments are accepted only from counterparties
charged about once a month, so a weekly supermarket shop is never a bill."""

HABITUAL_CHARGES_PER_MONTH: float = 1.5
"""Charges per active month above which an exact amount, or a counterparty's
variable spending, is a habit rather than a bill: a coffee most weekdays."""

RENAME_MIN_COMMON_CHARS: int = 5
"""Letters two names must share for a payment that stops to continue as one
that starts. A real subscription changed its printed name at the same price."""

TRUNCATED_KEY_MIN_CHARS: int = 8
"""Shortest name treated as a truncation of a longer one. AIB cuts at 18
characters, so 'EXAMPLE *VIDEO' is 'Example Videos'; a three-letter name is too short."""

RECURRING_GRACE_DAYS: int = 15
"""Days past the latest expected charge before a payment is reported stopped.
Covers weekends, bank holidays and late card postings."""

RECURRING_REPORT_WINDOW_DAYS: int = int(
    os.environ.get("FINCH_RECURRING_WINDOW_DAYS", "90")
)
"""How far back ``recurring`` looks for changes, starts and stops. A quarter, so
a monthly look does not miss the month before, and short enough to stay news."""


# ---------------------------------------------------------------------------
# Annotation page
# ---------------------------------------------------------------------------

UI_HOST: str = "127.0.0.1"
"""The annotation page listens on loopback only. It serves bank data and
accepts writes, so it must never be reachable from another machine; there is
deliberately no override."""

UI_PORT: int = int(os.environ.get("FINCH_UI_PORT", "0"))
"""Port for ``main.py ui``. 0 lets the system pick a free one each run: the
page's address carries a fresh token every start anyway, so a fixed port buys
nothing and can collide with another local server."""
