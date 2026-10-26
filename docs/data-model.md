# Data model

Each profile's ledger lives at `$FINCH_HOME/profiles/<name>/ledger.db`.
`main.py db schema` prints the live schema; the files under
`src/db/migrations/` carry the reasoning behind it.

## Tables

| Table | Holds |
| --- | --- |
| `accounts` | One row per bank account: name, institution, kind, currency, and at most the last four digits of its number. |
| `statement_imports` | One row per imported file: content hash, original filename, the parser and version that read it, the period and balances it claimed, rows seen and rows new. |
| `transactions` | Each transaction exactly as a statement reported it, with every source field kept verbatim in `raw_json`. |
| `transaction_sightings` | Every import that reported each transaction, with its row number in that file. |
| `documents` | One row per kept document (`doc add`): content hash, original filename, title, the date it carries and a note. The file itself is in the source archive. |
| `account_identifiers` | The owner's own IBAN and BIC for an account, typed in with `account details`. The only place a full account identifier is stored; no model reads it. |

There are no tables for merchants, categories, transfers or recurring payments
yet. Each arrives with the code that fills it.

## Conventions

- Amounts are signed integers in minor units. Negative is money leaving the account.
- Dates are ISO `YYYY-MM-DD` text; timestamps are UTC ISO-8601.
- `transactions` contains no interpretation. Nothing rewrites a stored row.
- `raw_json` keeps every source column verbatim, except sort codes and account
  numbers, which parsers cut to their last four digits wherever they appear.
  Full identifiers exist only in `account_identifiers`, entered by hand.

## Row identity

Banks export no transaction id. A row's identity key hashes its date, amount,
currency, whitespace-normalised description and printed balance, plus an
ordinal among rows that are otherwise identical in the same file. Two identical
purchases on one day stay two transactions.

Re-importing a file, or importing a statement that overlaps an earlier one,
adds only rows not already present, provided both files contain whole days.

Identity depends on how a parser reads a format. An import is therefore refused
when a different parser, or a different version of the same parser, already
imported transactions in its date range.

## Reconciliation

`main.py import` runs both checks below, and `--dry-run` reports their result
without writing.

**Inside a statement**, before anything is written: the file's account digits
match the account's `--last4` when both are known, and rows are oldest first,
inside the stated period and in the stated currency. Each printed balance must
equal the previous balance plus the rows since, and the rows must walk from the
opening balance to the closing balance. Any failure rejects the whole file and
nothing is archived or stored.

**Across the ledger**, after each import and in `status`: the same running
balance walk over the account's transactions in date order. A break here means
rows are missing between two statements, or an overlapping file disagreed with
an earlier one. It is reported rather than rejected, because a missing month is
often filled in later.

## Derived, not stored

What a transaction is — its channel, counterparty and foreign price, read from
the bank's text by the parser's `describe` — and which payments recur are
recomputed from `transactions` on every read. Nothing about them is stored, so
an improved rule applies to every past row without a rebuild or a parser version
bump. A table for derived facts arrives only when the owner can confirm or
correct one. See [recurring payments](recurring.md).

## Source archive

Every imported file is copied to
`$FINCH_HOME/profiles/<name>/sources/<sha256>/source.<ext>`, write-once and
owner-only. The original filename is recorded on the import row but not reused
on disk, since bank filenames often embed an account number. A file that no
longer matches its hash stops any further import of it.

Documents kept with `doc add` (contracts, letters, agreements) go into the same
archive, so every file a profile was given is in one place. `doc list` shows
each document and each statement with where its file is.
