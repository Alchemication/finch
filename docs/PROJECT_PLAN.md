# Project plan

The next steps, in the order agreed with Adam (2026-10-22, revised 2026-10-29). When a step is
done, take it out: git log keeps what was done, `docs/DECISIONS.md` what was
decided and why. Each step is used on real data before the next starts, so the
order is a hypothesis to revise.

finch succeeds when it changes what the household pays. Keep a savings log
under `FINCH_HOME` (never in the repository): one line per action finch
prompted, with its effect in euros a year. If the log is empty after three
months of real use, the plan is wrong, however good the code.

## Now

Until the register exists, facts the ledger cannot hold (rates, term ends,
assets, things to check) live in a private `notes.md` in the profile's
directory, beside the savings log.

1. **Backups.** The ledger, the archive and the notes exist on one Mac, and
   Time Machine's disk stopped mounting. Everything in one place makes this
   the largest risk in the plan. Restore Time Machine, and add one encrypted
   copy off the machine; check a restore once.

2. **Skills for what is done by hand.** Three procedures were repeated in
   Claude Code sessions in October 2026 and should become project skills, so
   the next run follows the same steps. Each later becomes code and a chat
   tool.
   - Document intake: read a file, decide what it belongs to, extract facts
     and dates, `doc add`, update the notes, set reminders.
   - Statement check, before any import: format, balance walk, overlaps,
     identical files, gaps, row caps.
   - The annual tax return: Irish reliefs to claim (pension backdating, health
     insurance, medical expenses, remote working, foreign dividends, gains,
     deposit interest), each with its source and the date checked.

3. **Categories, reviewed** (`docs/DECISIONS.md`: categories before the
   household). Built: one category per payment from labels, payee rules and
   payment type, proposals awaiting review, `spend`, and the local annotation
   page (`main.py ui`, `docs/categories.md`). The first pass failed: every
   payee waited on a click, and 608 is not a queue anyone works through.
   Next:
   - Keyword rules in code, with tests, for payees whose name says what they
     are (supermarkets, fuel, pharmacies, the mortgage, the crèche). Like
     channel defaults they apply without review; the owner corrects the odd
     miss, and a correction beats the rule.
   - Review only what is material: the payees and one-off payments making up
     most of the money still unclassified, a few dozen at most. The long tail
     stays unclassified, shown as a count.
   - Adam labels the salary credits and the big one-off transfers.
   - Then medical payments listed per tax year with what may qualify for
     relief, and receipts kept with `doc add`.

4. **The household ledger** (`docs/DECISIONS.md`: household from day one).
   - A profile becomes a household: a `people` table, and every account owned
     by one person or held jointly (`account add --owner`). Every document,
     note and decision records who added it. `main.py`, README
     and `docs/data-model.md` stop saying "one profile per person".
   - Agreed with Adam's wife (2026-10-28): her whole Bank of Ireland current
     account goes in, and Claude may read it.
   - Her BOI parser and backfill, from the desktop export (the mobile app's
     export gives three months and its balance column does not reconcile).
     The desktop export prints an end-of-day balance on each date's first
     row, and it walks. It stops at 240 rows, so a long range is cut off,
     often in the middle of its last date. To decide: whether an import may
     drop a final date whose balance does not walk, report it, and land the
     rest, the next file bringing that date whole. Every other mismatch still
     refuses the file. The first files leave a gap of about ten weeks, asked
     for.
   - Transfers between household accounts paired and netted out, so moving
     money between partners or into the joint account is never spending.
     Derived on every read like `recurring`; only the owner's corrections are
     stored.

5. **The register** (`docs/DECISIONS.md`: a register of things owned). One
   place for everything the household owns or owes: the house, land, cars,
   pensions, accounts, investments, the mortgage, car finance, contracts and
   subscriptions. Each thing has owners, short dated facts with their source and who
   added them,
   dated valuations, linked documents and letters, and deadlines. Net worth is
   computed from the latest valuations and balances, grouped as available,
   locked and owed, with unknowns listed. Context that is only read (why a
   plot was bought) stays a short markdown note per thing; only what is
   compared or added up goes in tables. The commitments the plan first
   called a register (every recurring outflow with provider, price history
   and renewal date, from `recurring` plus the owner's confirmations) are
   things in it. `notes.md` is moved in and retired. The first renewal is
   reviewed by hand in a Claude Code session (`docs/DECISIONS.md`: research
   by hand first), and its evidence kept.

6. **Chat**, for Adam and his wife (`docs/DECISIONS.md`: the whole household
   visible; Telegram for words, one-time pages for files). A Telegram bot on
   the Mac mini, starting from zdrowskit's `llm.py`, tables, eval framework,
   chat and SQL tool, with the safeguards in `docs/DECISIONS.md` (read-only
   SQL). Read-only at first; both partners are allowed users and see the
   whole household. It answers from the register and the ledger: what is
   due, what a thing is worth and why, where a document is, what was spent,
   and says who owns each thing and who added each fact. Figures come from
   functions. It reminds both of deadlines before they fall. Documents and
   account details are never sent through Telegram or read by a model: the
   bot replies with a one-time link to a finch page on the Mac mini, opened
   over the household's Tailscale network (not Funnel), so it reaches only
   their devices. finch listens on the Mac mini alone; the route in is set up
   outside finch, so a Cloudflare Tunnel behind Cloudflare Access can replace
   Tailscale without code changes if Tailscale proves flaky. The one-time
   link is checked by finch either way. The annotation page's loopback guards
   (host check, per-start token) are redesigned for that route. Questions are logged: the ones asked twice
   become the weekly check.

7. **Statement access.** An hour's spike: link AIB to Enable Banking in
   restricted mode, pull 90 days, and compare with the CSV for price, history
   depth, description length and balances. Then decide between the API and a
   scheduled browser download (`docs/DECISIONS.md`: CSV first). Until then,
   import from a watched drop folder, and say when the ledger is stale.

8. **The weekly check.** Silent unless something material changed: salary
   missing, late or changed; a new recurring payment or a confirmed price
   rise; a duplicate charge; a renewal or deadline coming up; the balance
   projected below a floor before payday; a stale ledger or a balance break.

## Later, as gaps show

Not ordered. Each waits until real use shows it is needed.

- Renewal research automated, once the hand-run procedure has settled into a
  skill.
- A fixed or discretionary flag per category, if reports need it.
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
- Investment holdings priced automatically. Until then a holding's value is
  a dated valuation in the register; CashAsh stays the source for the stock
  portfolio.
- Who owes whom between partners, if the household ever settles up that way.

## Open questions

- What leaves the machine once models are involved: whether merchant names and
  amounts are sent verbatim, which providers' retention terms are acceptable,
  and whether a local model is good enough to pick tools. Telegram bot chats
  are not end-to-end encrypted: whatever the bot sends is held on Telegram's
  servers.
- Whether a Revolut or credit card on either side carries spending the
  current accounts never see.
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
