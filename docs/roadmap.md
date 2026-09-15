# Roadmap

What is not built yet, in the order it is expected to land. Each step is used on
real data before the next starts, so the order is a hypothesis to revise.

## 1. AIB backfill

Import the 24 months AIB's Historical Transactions export allows. Done when
every file imports without a reconciliation problem and `status` shows no
balance breaks.

## 2. Knowing what each transaction is

Channels, counterparties and recurring payments are built. Still to come:

- Owner confirmations for recurring payments: rename, not recurring, cancelled.
  This is the first derived fact worth storing, as a correction.

- Merchants and the aliases banks print for them, with a confirmed-alias rule
  table so a merchant is identified once.
- A small category tree with a fixed or discretionary flag.
- Links between rows: transfer between own accounts, refund of, reimbursement of.
- An append-only classification table recording source (rule, model or owner),
  confidence and what superseded it. Unclassified is a visible state.

The LLM layer arrives here, for merchant strings rules cannot identify. Copy it
from zdrowskit. The first eval is a labelled set of the operator's own
transactions, which also measures how much rules alone already cover.

## 3. The monthly close

One report per month: income, spend by category against the trailing median,
recurring changes, transfers netted out, savings rate, and everything the ledger
could not explain. Figures are frozen when the report is written, so
reclassifying an old row cannot silently rewrite an old report.

Read-only chat over the ledger, with money computed by functions rather than
model-written SQL, and CashAsh's proposal pattern for corrections.

## 4. Second profile

A Bank of Ireland parser and a second, isolated profile.

## 5. Delivery

Telegram delivery of the monthly close, a review queue for low-confidence
classifications, and a weekly check that stays silent unless something material
changed.

## 6. Automated statement download

Scheduled browser download, built on what CashAsh's Revolut downloader learns.
Bank sessions expire and need phone approval, so a scheduled run reports
"sign-in required" instead of opening a browser unannounced.

## 7. Beyond the current account

Savings, pension, mortgage and investment balances as dated snapshots, and net
worth from them. CashAsh stays the source for the stock portfolio.

## 8. Contracts and research

Services with provider, contract end date and usage, and a renewal review that
researches alternatives only when the saving is material. Every recommendation
keeps its evidence: source, retrieval date, and what was compared.

## Not planned

- Merging household profiles into one ledger.
- Open-banking aggregators. Consent must be renewed every few months, which is
  the same attended re-authentication as a browser download, with a third party
  holding the data.
- Budgets and dashboards. The output is a short explanation of what changed.

## Open questions

- Whether one AIB export can span 24 months, or the site limits the range per file.
- Whether a card refund carries the same description as the purchase it reverses.
- Whether AIB's truncated 18-character descriptions identify merchants well
  enough, or the full payee names in Payment Logs are needed.
- Whether purchase dates matter. Card payments carry only their posting date,
  which is fine for monthly figures and too coarse for weekday patterns.
- How much of the ledger rules identify without a model.
- What leaves the machine once models are involved: whether merchant names are
  sent verbatim, and which providers' retention terms are acceptable.
