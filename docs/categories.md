# Categories

Every transaction has one category, worked out from the owner's decisions each
time it is read. Nothing is written onto the bank's rows, so correcting a
payee's category changes all of its history at once.

```bash
uv run python main.py ui                      # the annotation page
uv run python main.py spend                   # per year
uv run python main.py spend --monthly         # per month
uv run python main.py category unclassified   # what nothing names yet
```

## How a transaction gets its category

First match wins:

1. **A label** on that one transaction, set by the owner. For payments no payee
   rule can name: a transfer whose reference is typed per payment, or one
   payment unlike the rest from the same payee.
2. **The payee's confirmed rule**, by counterparty key (see
   [recurring payments](recurring.md) for how keys are made). A rule set to
   no category keeps the payee unclassified.
3. **The payment type**: cash withdrawals are Cash, bank charges are Fees.
4. **Unclassified**, shown as such in every report, never folded into another
   category.

`main.py category list` prints the categories. Transfers and income categories
are kept apart from spending in reports.

## Proposals and review

A model (for now, Claude in a Claude Code session) may propose a category for a
payee, with a confidence and a note. A proposal applies to nothing until the
owner confirms it; confirming, correcting or rejecting adds the owner's
decision as a new rule, and the proposal stays in the history it superseded.

```bash
uv run python main.py category propose proposals.json
uv run python main.py category review [--category SLUG]
uv run python main.py category confirm --category groceries --except SOMEKEY
uv run python main.py category confirm --key SOMEKEY
uv run python main.py category set SOMEKEY travel --note "Holiday hotel"
uv run python main.py category set SOMEKEY none
uv run python main.py category label income-salary 625 724 --note "Pay"
```

A proposals file is a JSON list of `{"key", "category", "confidence", "note"}`,
`confidence` one of `high`, `medium`, `low`. It holds real payee names, so it
lives under `FINCH_HOME`, never in the repository. Proposals for payees the
owner already decided are skipped.

## The annotation page

`main.py ui` serves a page on `127.0.0.1` and opens it in the browser:

- **To review**: proposals, each with a one-click accept, or a type-to-filter
  category picker to choose another. Accept all high-confidence proposals
  shown, or a selection.
- **Unclassified** and **All payees**: search, filter by category, sort by
  money, recency or payments.
- **A payee's payments** open in a side panel, where one payment can be
  labelled differently, with a note saying what it was.
- **Insights**: spending by category per year, net of refunds, with each
  category's month-by-month line and the unclassified total shown in amber.

Keyboard: `j`/`k` move, `a` accepts, `c` chooses, `n` marks no category,
`o` opens payments, `x` selects, `/` searches, `1`–`4` switch tab, `?` lists them.

The page is local only. It listens on loopback, its address carries a token
that changes every start, and it refuses requests naming another host or
coming from another site. It loads nothing from the internet. `--port` and
`FINCH_UI_PORT` choose the port; by default a free one is picked.

## Known limits

- One category per transaction. A supermarket shop that included a toy is
  groceries.
- Rules match a payee's key exactly. Salary paid under a new reference each
  month needs a label per payment, not a rule.
- Unclassified money in is not treated as a refund: until named, it does not
  reduce any spending figure.
