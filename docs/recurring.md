# Recurring payments

`main.py recurring` finds the payments that repeat: subscriptions, direct
debits, regular transfers and salary. It reports what they cost a month, which
changed price, and which started or stopped.

```bash
uv run python main.py recurring
uv run python main.py recurring --window-days 30
uv run python main.py recurring --all
```

The report is as of the ledger's latest transaction, not today, so a ledger
that has not been refreshed does not report every payment as stopped. Price
changes, starts and stops look back `--window-days` from that date; the default
is `RECURRING_REPORT_WINDOW_DAYS` in `src/config.py`. `--all` also lists
payments that have stopped.

Nothing is stored. Series are recomputed from transactions on every run, so a
new import or a better rule changes every past month at once.

## What counts

- Charges at a regular cadence: monthly, quarterly or annual. One missed month
  does not break a monthly series.
- A monthly or quarterly payment needs `RECURRING_MIN_CHARGES` charges. An
  annual one needs `ANNUAL_MIN_CHARGES` charges at one fixed price, above
  `ANNUAL_MIN_AMOUNT_MINOR`.
- Fixed-price payments on any channel. Varying amounts are accepted for direct
  debits, bank fees and incoming transfers, and for card payments to a
  counterparty charged about once a month.
- Transfers are matched on amount and timing, not reference, because
  references are typed per payment. A monthly transfer to one payee is one series
  under many names; the latest name is shown.
- Prices are compared in the currency the merchant charged when the bank
  reports it, so exchange-rate movement is not a price change.
- Several subscriptions billed by one merchant, such as an app store, are separate
  series.

## What does not

- Cash withdrawals and card refunds.
- Habits: one exact amount bought more than `HABITUAL_CHARGES_PER_MONTH` times a
  month, such as a daily coffee.
- Varying card spending at a counterparty charged more often than that, such as
  a weekly supermarket shop.
- Irregular visits at one price, such as a haircut every six to ten weeks.

## Price changes

A change is reported when a charge differs from the series' established price
by at least `PRICE_CHANGE_MIN_PCT` and the next charge confirms it. A change on
the latest charge is shown as unconfirmed. A single odd charge that reverts is
ignored. Series whose amount varies report no changes, since every charge would
read as one. The yearly effect is shown for prices in the account's currency.

## Names

A name that is a truncation of exactly one longer name joins it: AIB cuts
descriptions at 18 characters. A payment that stops and resumes one period later
at the same price, under a name sharing `RENAME_MIN_COMMON_CHARS` letters, is
one payment renamed.

## Known limits

- A new subscription appears only after enough charges to count.
- A price step larger than the tolerance starts a new series instead of
  continuing the old one, and a plan change such as a downgrade shows as one
  payment stopping and another starting.
- Two different transfers at the same amount and timing merge.
- Coincidences survive among stopped payments, such as road tolls or parking
  charged a few months in a row. They are hidden unless `--all` is given.
- Card payments carry their posting date, so a subscription billed on the 30th
  can post on the 1st or 2nd.

Every threshold lives in `src/config.py` with the observation that set it.
