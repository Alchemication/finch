# AIB exports

The `aib-csv` parser reads the CSV that AIB internet banking produces for a
current account from **Historical Transactions**, then **Export**. Historical
transactions reach back at most 24 months.

```bash
uv run python main.py import ~/Downloads/Transaction_Export_....csv --dry-run
uv run python main.py import ~/Downloads/Transaction_Export_....csv
```

## What the file contains

- One row per posted transaction, oldest first, with the balance after every row.
- Posting dates as `DD/MM/YYYY`. For card payments this is when the bank posted
  the payment, not when it was made; weekend and bank-holiday spending posts on
  the next working day.
- Exactly one of Debit Amount and Credit Amount, unsigned, with comma thousands
  separators.
- Description1, cut to 18 characters, usually with a prefix: `VDP-` and `VDC-`
  for card payments, `VDA-` for cash withdrawals, `D/D` for direct debits.
  Credit transfers and bank fees have none.
- Description2 and Description3 with per-row detail: a direct-debit reference
  that changes every collection, a foreign amount and rate for card payments in
  another currency, a cash machine's town and withdrawal time, or a transfer date.
- Transaction Type, seen so far as `Debit`, `Credit`, `Direct Debit` and `ATM`.
- Posted Account, as sort code and account number. Quarterly fee rows also
  print the sort code and account number in Description2.

## What it does not contain

- Pending card payments, which the website lists separately until they post.
- Full payee names. The website's Payment Logs show direct-debit payees in
  full, with upcoming collections.

## How the parser treats it

- The ledger description is Description1 verbatim. Every other column stays in
  the row's raw fields, and Transaction Type becomes the bank reference.
- Sort codes and account numbers are cut to their last four digits in every
  column before anything is kept.
  An import is refused when those digits differ from the account's `--last4`.
- Anything affecting a figure that falls outside the layout above is an error
  naming the row: a changed header, both or neither amount filled, a signed
  amount, a local currency amount that differs from the posted amount, a second
  account or currency in one file, or a file that is not UTF-8.
- A Transaction Type not seen before is accepted and kept verbatim, since the
  amount columns alone decide direction.

## How rows are described

`describe` reads each stored row for `recurring` and later features. Nothing it
produces is stored.

- `VDP-` and `VDC-` are card payments, `VDA-` cash withdrawals, `D/D` direct
  debits, and `*INET` and `*MOBI` transfers sent. The prefix is removed from the
  counterparty.
- When Description1 is only a SEPA reference, `IE` and 14 digits, Description2
  holds the payment's text and is read instead.
- Quarterly and monthly account fees, stamp duty and payment fees are bank fees.
- Any other credit is a transfer received, such as salary or a refund by
  transfer. Any other debit is `other`.
- A Description2 such as `12.50 USD@` gives the price in the currency charged.
