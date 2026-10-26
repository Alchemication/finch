# Project plan

The next steps, in the order agreed with Adam (2026-10-22). When a step is
done, take it out: git log keeps what was done, `docs/DECISIONS.md` what was
decided and why. Each step is used on real data before the next starts, so the
order is a hypothesis to revise.

finch succeeds when it changes what the household pays. Keep a savings log
under `FINCH_HOME` (never in the repository): one line per action finch
prompted, with its effect in euros a year. If the log is empty after three
months of real use, the plan is wrong, however good the code.

## Now

Until the commitments register exists, facts the ledger cannot hold (rates,
term ends, assets, things to check) live in a private `notes.md` in the
profile's directory, beside the savings log.

1. **The household ledger** (`docs/DECISIONS.md`: household from day one).
   - A profile becomes a household: a `people` table, and every account owned
     by one person or held jointly (`account add --owner`). `main.py`, README
     and `docs/data-model.md` stop saying "one profile per person".
   - Before any of her data: agree with Adam's wife which of her accounts go
     in (personal card spending, or joint only) and whether a model may read
     them.
   - Her bank's parser (Bank of Ireland, to confirm), and her backfill.
   - Transfers between household accounts paired and netted out, so moving
     money between partners or into the joint account is never spending.
     Derived on every read like `recurring`; only the owner's corrections are
     stored.

2. **The commitments register.** Every recurring outflow with its provider,
   price history and renewal date, from `recurring` plus the owner's
   confirmations: rename, not recurring, cancelled, renewal date. The first
   derived facts worth storing, as corrections. It also holds the dated events
   no statement shows in advance: a fixed mortgage rate ending, a car finance
   agreement's final payment. Adam and his wife fill in the contracts that
   renew in the next six months, starting from `notes.md`. The first renewal
   is reviewed by hand in a Claude Code session (`docs/DECISIONS.md`: research
   by hand first), and its evidence kept.

3. **Chat.** Telegram chat over the ledger, starting from zdrowskit's `llm.py`,
   tables, eval framework and SQL tool, with the safeguards in
   `docs/DECISIONS.md` (read-only SQL). Questions are logged: the ones asked
   twice become the weekly check. Needs the decision on what leaves the
   machine first (open questions below).

4. **Statement access.** An hour's spike: link AIB to Enable Banking in
   restricted mode, pull 90 days, and compare with the CSV for price, history
   depth, description length and balances. Then decide between the API and a
   scheduled browser download (`docs/DECISIONS.md`: CSV first). Until then,
   import from a watched drop folder, and say when the ledger is stale.

5. **The weekly check.** Silent unless something material changed: salary
   missing, late or changed; a new recurring payment or a confirmed price
   rise; a duplicate charge; a renewal coming up; the balance projected below a
   floor before payday; a stale ledger or a balance break.

## Later, as gaps show

Not ordered. Each waits until real use shows it is needed.

- Renewal research automated, once the hand-run procedure has settled into a
  skill.
- Categories, only as far as decisions need: fixed or discretionary, and a few
  buckets. Unclassified stays visible.
- Merchants and the aliases banks print for them, with a confirmed-alias table.
  Claude Haiku 5.5 is the candidate model for rows rules cannot identify:
  fast and cheap enough to run over the whole ledger.
- Refunds and reimbursements linked to what they reverse.
- Tax reliefs claimable from evidence already in the statements.
- Payslips as a source: gross pay, tax, and pension contributions from both
  employee and employer. Pension contributions made through payroll never
  reach a bank account, so without them a savings rate can read as zero for a
  household that saves a fifth of gross pay. They also give the headroom under
  the age-related limit on pension tax relief.
- Savings, pension, mortgage and investment balances as dated snapshots, and
  net worth from them. CashAsh stays the source for the stock portfolio.
- Who owes whom between partners, if the household ever settles up that way.

## Open questions

- What leaves the machine once models are involved: whether merchant names and
  amounts are sent verbatim, which providers' retention terms are acceptable,
  and whether a local model is good enough to pick tools.
- Which of Adam's wife's accounts the household covers, at which banks, and
  whether a Revolut or credit card carries spending the current accounts never
  see.
- What counts as material, in euros a year.
- Enable Banking's price for restricted mode: its FAQ describes volume pricing,
  while third parties report personal use as free.
- Whether a card refund carries the same description as the purchase it
  reverses.
- Whether AIB's 18-character descriptions identify merchants well enough, or
  the full payee names in Payment Logs (or an API) are needed.
- Whether purchase dates matter. Card payments carry only their posting date,
  which is fine for monthly figures and too coarse for weekday patterns.
- How much of the ledger rules identify without a model.
