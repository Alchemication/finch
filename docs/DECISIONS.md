# Decisions

What has been decided, and why, so it isn't reopened by accident. Each one can
change: say so, and update it here. The working rules that follow from them
(evidence rows, integer money, strict reconciliation, privacy) are in
`CLAUDE.md`; what to build next is in `docs/PROJECT_PLAN.md`.

## Scope

- **For one household, not a product.** Built for Adam and his wife. Other
  couples' arrangements are not design inputs.
- **Household from day one** (Adam, 2026-10-22). Couples share expenses, and
  Adam and his wife do. A one-person ledger also gets its own totals wrong:
  money moved to a partner or a joint account reads as spending. So a profile
  is a household, and each account is owned by one person or held jointly.
  Adding owners before real data is one migration; after, it is a data
  migration and a re-check of every derived fact. This reverses the earlier
  "no merged household profiles". What of her own spending goes in is her
  decision. Who-owes-whom settlement waits until the household needs it.
- **Savings before categories** (2026-10-22). Contracts at renewal (mortgage,
  energy, insurance, broadband, mobile) save the most, then subscription creep
  and price rises, then idle cash, then reliefs; discretionary spending
  patterns save the least and least reliably. So the commitments register
  comes before categories, and categories go only as far as decisions need.
- **No budgets or dashboards.** The output is a short explanation of what
  changed and what it costs a year. Category totals answer a question asked;
  they are not pushed.

## Data in

- **CSV exports first; open banking reconsidered after a spike**
  (2026-10-22). The backfill needs CSVs anyway: AIB's export reaches 24 months,
  while banks' APIs typically give full history only for about an hour after
  consent, then 90 days. Open banking was first rejected for re-consent effort
  and a third party holding the data. Re-checked: GoCardless's free Bank
  Account Data closed to new signups in 2025; Enable Banking covers AIB and
  Bank of Ireland, offers a restricted mode for one's own accounts, and allows
  up to 180 days' consent at most banks, so about two approvals a year. Its
  price for this use is unconfirmed. API rows usually carry no running
  balance, so an API source would reconcile against balance snapshots instead
  of printed per-row balances, and would cover only dates after the last CSV,
  since sources may not overlap. A scheduled browser download stays the
  fallback.

## Models

- **Model-written SQL is allowed, read-only** (Adam, 2026-10-22). One
  household's tool, nothing written, and ad-hoc questions no function
  anticipates. The risk is a plausible wrong number, not a write: a sign
  convention, cents read as euros, an internal transfer counted as spending,
  currencies summed together. So: the connection is read-only by construction
  (`mode=ro`, `query_only`, an authorizer refusing `ATTACH`), with a time limit
  and a row cap; curated views are the model's main surface; figures a
  function computes come from that function; every answer can show its SQL and
  row count; an eval set of questions with known answers catches quiet errors.
  Query results go to the model provider, which is the open question on what
  leaves the machine (`docs/PROJECT_PLAN.md`).
- **Research by hand first** (2026-10-22). Alternatives at renewal are
  researched in Claude Code sessions, as re-kid researches its worlds, and
  written down with source, retrieval date and what was compared. A research
  agent in the daemon waits until the procedure has settled into a skill.
