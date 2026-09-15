## Rules

Always use `uv run`, never plain `python`. Commands: `uv run python main.py --help`.

Open databases with `store.open_existing_db()`, which applies pending migrations
and refuses to create a file. Only `main.py init` calls `store.open_db()`, so a
wrong profile or `FINCH_HOME` fails loudly instead of showing an empty ledger.

Schema changes go in new timestamped migration files under `src/db/migrations/`.
No ad-hoc `ALTER TABLE`, column-existence checks, or schema patching in
application code. A table arrives with the code that fills it, never ahead of it.

**Bank rows are evidence, never edited.** `transactions` holds what a statement
said and nothing else; every source field survives in `raw_json`, except sort
codes and account numbers, which parsers cut to their last four digits in every
field (`parsers.common.mask_account_numbers`).
Interpretations — merchant, category, transfer pairing, refund matching,
recurring series — go in their own tables with source, confidence and
supersession, because they get corrected and a correction must not overwrite
what it corrects.

**Money is integer minor units.** Parse with `money.parse_amount`, format with
`money.format_minor`. No float holds an amount anywhere, tests included.

**An import that does not reconcile does not land.** A statement whose rows do
not walk from its opening balance through every printed balance to its closing
balance is rejected whole, with nothing written. Parsers are strict: an unknown
column, row shape or amount format is an error, never a guess.

**The ledger is rebuildable from the archive.** Every imported file is kept,
write-once, under the profile's `sources/<sha256>/`. Imports are idempotent by
content hash and per-row identity key. Mixing parsers or parser versions over
the same dates is refused, because identity keys differ between them. Fix a
parser by bumping its version and rebuilding, not by patching rows.

**Unknown stays visible.** An unclassified transaction, an unverifiable balance
or a missing month is reported as such. Never fold it into "Other" or a zero.

**Derived facts are recomputed, not stored.** Channels, counterparties and
recurring series come from `transactions` on every read (`describe.py`,
`recurring.py`), so a better rule applies to all history at once. Store a
derived fact only when the owner confirms or corrects it, and then store the
correction, not the derivation.

**Deterministic before LLM.** Every figure, match, total and detection is code
with tests. A model may propose an interpretation of an ambiguous row, explain
a change, or research an alternative. What it proposes is stored with source and
confidence, and becomes a rule only once the owner confirms it. Neither SQL a
model writes nor a model's prose computes money a function already computes.

**No personal data in the repository.** Statements, account numbers, amounts,
real merchant names and keys live under `FINCH_HOME`, never in tracked files;
git history is permanent. This covers every tracked file: unit tests, fixtures,
LLM eval cases, prompts, docstrings, comments, docs and commit messages. Use
invented merchants, references, amounts and dates that keep the shape under
test — a price step, a drifting date, a truncated name — never the real values.
An eval case derived from a real LLM call is rewritten the same way before it
is committed, and refers to that call only by id. Never log a
transaction description, IBAN or full account number: problems name a row by
number and date. Store at most the last four digits of an account number.

**`FINCH_HOME` stays off synced folders.** The default is under
`~/Library/Application Support`, not `~/Documents`, which iCloud may sync:
that uploads statements to a third party and can corrupt an open SQLite
database. Private directories are `0700`, files `0600`, and nothing private is
written inside the checkout.

Operational tunables — thresholds, limits, windows — live in `src/config.py` as
named constants, each with a docstring saying how the value was chosen. Never
inline them at the point of use.

Work on `main` and push straight to it — no feature branches, no PRs. Single
developer. Commit only when asked, and only with lint and tests green.

## Sibling projects

`../zdrowskit` and `../cash-ash` share this skeleton: profiles under an app home,
timestamped migrations, `config.py` tunables, dispatch-only `main.py`. They are
reference implementations, not dependencies.

There is no LLM layer yet. When the first model call lands, start from
zdrowskit's `llm.py`, `model_prefs.py`, its `llm_call` / `llm_trace` /
`llm_feedback` tables and its eval framework, which are the battle-tested
versions. zdrowskit's cases copy the fixture of a real call; here a case
keeps a real call's shape but never its figures, names or dates. Take CashAsh's proposal pattern (`proposals.py`, `pending_write`) for
any write a model suggests. Do not extract a shared package until finch has run
on real data for a month and all three copies' actual needs are known.

## Collaboration Style

Challenge my ideas early. If an approach is over-engineered, fragile, or has a
simpler alternative — say so directly with reasoning. Flag knowledge gaps,
hidden trade-offs, or narrowed thinking. Be pragmatic; save me from wasting
time on something that could be done better.

**Prose:** terse, no pleasantries / hedging / filler. Fragments fine. Full
sentences only for warnings, destructive-op confirmations, and commit/PR
messages.

**Verification:** After cross-cutting changes (multiple modules, interface
changes, file moves), verify before reporting done. Grep for stale references,
check callers of changed functions, confirm imports, run lint + tests, and fix
what you find — don't wait to be asked.

## Documentation

Any change to user-visible behavior, commands, defaults, limits, paths, storage
or workflows must audit and update `README.md`, `docs/*.md` and `.env_example`
in the same commit, even when the code change is small.

Docs describe current behavior, not history or plans — except
`docs/roadmap.md`, which is explicitly about what is not built yet.

Docs name the knob and the command that prints its value; code owns the value.

Keep `AGENTS.md` and `CLAUDE.md` identical. When editing either, update both.

## Code Style

- **Linter/formatter:** `uv run ruff check .` and `uv run ruff format .`
- **Type hints:** required on all signatures. Native types only (`list`, `dict`, `str | None`) — never `typing.List` etc.
- **Docstrings:** Google style.
- **File size:** keep source files under ~1000 lines; extract a cohesive subset when one grows past that.
- **No backward-compat shims:** when moving code, update all callers. No re-export stubs.

## Output Rules

- `print()` for user-facing content (reports, JSON) → stdout.
- `logger` (stdlib `logging`) for diagnostics, progress, errors → stderr.
- `rich` (import lazily inside the handler) for structured terminal display.
- Error messages should tell the user what to do, not just what went wrong.

## Testing

`uv run pytest`. Fixtures in `tests/conftest.py`; synthetic statement builders in
`tests/factories.py`.

**Must have tests:** every parser and describer, against synthetic files shaped
exactly like the real layout; amount parsing; identity keys; balance
reconciliation; import idempotence and overlap; store round trips; recurring
detection, including the false positives it must reject; anything that computes
money.

**Style:** group in classes (`class TestImportStatement`); use the `conn` and
`account` fixtures and `tmp_path`; cover edge cases that would silently break
(None, empty statements, identical rows, overlaps); run ruff on `tests/` before
committing.

## Code map

`main.py` is dispatch only. Layers, bottom up:

- `src/db/migrations/` — versioned schema, one file per change
- `src/models.py` — dataclasses with input validation, no persistence
- `src/money.py` — integer minor units: strict parsing and formatting
- `src/store.py` — SQLite read/write, no business logic, never commits
- `src/profiles.py` — roster, per-profile paths, private directories
- `src/sources.py` — write-once private archive of imported files
- `src/ledger.py` — derived facts: running-balance walks, latest balance
- `src/ingest.py` — validates a `ParsedStatement` and writes it, or refuses
- `src/parsers/` — one module per bank format, returning a `ParsedStatement`
  and never touching the database; `parsers.detect` picks one by content
- `src/describe.py` — channel, counterparty and grouping key for stored rows
- `src/recurring.py` — recurring series, price changes, report window
- `src/commands.py`, `src/cmd_import.py`, `src/cmd_recurring.py` — CLI handlers
  and rendering

A parser records the layout it was written against in its module docstring and
in `docs/<bank>.md`, and rejects anything affecting a figure outside it. When a
real file breaks a parser, extend the synthetic fixture to that shape first.
