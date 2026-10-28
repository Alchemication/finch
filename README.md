# finch

A personal financial ledger that knows where the money went, built to grow into
an adviser that has read every statement.

Named for the finch, a small bird that notices everything, and for Harold Finch
of *Person of Interest*: it watches the numbers quietly, speaks up only when
something matters, and treats privacy as a first principle.

**Status: ledger, AIB import and recurring payments.** Profiles, the ledger
database, a reconciling import of AIB current account exports, and detection of
recurring payments with their price changes work, as do categories with a local
annotation page and a spending report. Transfer matching is not built yet. See the [project plan](docs/PROJECT_PLAN.md).

## How it works

Bank exports are the input. Each file is checked against the running balance it
prints, archived, and written as transactions that record what the bank said
and nothing more. Anything derived — channels, counterparties, recurring
payments, later categories and transfers — is recomputed from those rows on
every read, so a wrong guess never damages the evidence.

Data stays local, in SQLite under `FINCH_HOME`. Nothing calls an LLM yet.

## Requirements

- macOS or Linux
- Python 3.12+ and [uv](https://github.com/astral-sh/uv)

## Quick start

```bash
uv sync
uv run python main.py profile add me --operator
uv run python main.py init
uv run python main.py account add aib-current --institution AIB --kind current --last4 1234
uv run python main.py import ~/Downloads/Transaction_Export.csv --dry-run
uv run python main.py import ~/Downloads/Transaction_Export.csv
uv run python main.py status
uv run python main.py recurring
```

Use the real last four digits of the account number: an import is refused when
the file belongs to a different account. [AIB exports](docs/aib.md) explains
where the file comes from and what it contains.

## Where data lives

`FINCH_HOME` defaults to `~/Library/Application Support/finch`; override it in
`.env` (see `.env_example`). Keep it on a local, encrypted disk. `~/Documents` is
a poor choice on a Mac with iCloud Desktop & Documents sync: it uploads bank
statements to iCloud and can corrupt a SQLite database synced while open.

```text
$FINCH_HOME/
  profiles.toml
  profiles/<name>/
    ledger.db
    sources/<sha256>/source.<ext>    statements and kept documents
    proposals/                       category proposals, as JSON
```

Directories are created `0700` and files `0600`. Nothing private may be written
inside the repository.

## Commands

| Command | Does |
| --- | --- |
| `profile add NAME [--operator]` | Create a profile. The first one must be the operator, the default for every other command. |
| `profile list` | List the roster. |
| `init` | Create the profile's ledger database. The only command that creates one. |
| `account add NAME --institution BANK --kind KIND` | Register an account. `--currency` and `--last4` are optional. |
| `account list` | List accounts. |
| `account details NAME [--iban IBAN] [--bic BIC]` | Show an account's IBAN, BIC, sort code and account number, or store them. The IBAN is checked by its check digits and must end in the account's `--last4`. |
| `import FILE [--account NAME] [--dry-run]` | Import a bank export. `--dry-run` reports what would change and writes nothing. Re-importing a file, or an overlapping one, adds only new rows. |
| `recurring [--account NAME] [--window-days N] [--all]` | Subscriptions, bills, transfers and pay that repeat: monthly cost, price changes, and payments started or stopped recently. |
| `status` | Per account: transactions, date coverage, balance, imports, and balance breaks. |
| `doc add FILE --title TITLE [--date YYYY-MM-DD] [--note TEXT]` | Keep a contract, letter or agreement in the private archive. Adding the same file again changes nothing. |
| `doc list` | Every kept document, and every imported statement with where its file is archived. |
| `doc open N` | Open kept document N. |
| `ui [--port N] [--no-open]` | Open the local annotation page: review proposed categories, name payees and payments, and see spending by category. |
| `spend [--monthly] [--months N]` | Money out and in by category, per year or per month, net of refunds, with unclassified shown. |
| `category unclassified [--limit N]` | The biggest payees and payments nothing has named yet. |
| `category review` / `confirm` / `set` / `label` / `propose` / `list` | Review and confirm proposed categories, name a payee or a payment yourself. See [categories](docs/categories.md). |
| `db status` / `db schema` | Migration state and row counts, or the live schema. |

Every command except `profile` takes `--profile NAME`. Run any command with
`--help` for its flags.

## More

- [AIB exports](docs/aib.md) — getting the file, and what the parser accepts
- [Recurring payments](docs/recurring.md) — what counts, price changes, known limits
- [Categories](docs/categories.md) — how a payment gets its category, review, the annotation page
- [Data model](docs/data-model.md) — tables, conventions, row identity, reconciliation
- [Project plan](docs/PROJECT_PLAN.md) — what comes next, and open questions
- [Decisions](docs/DECISIONS.md) — what has been decided and why
- [Principles](docs/PRINCIPLES.md) — how finch should feel, and what it must never do

## Development

```bash
uv run pytest
uv run ruff check .
uv run ruff format .
```

`AGENTS.md` and `CLAUDE.md` hold the coding rules.
