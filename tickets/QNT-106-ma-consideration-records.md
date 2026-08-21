# QNT-106 — Historical M&A consideration records

- **Ticket ID:** QNT-106
- **Status:** BACKLOG
- **Priority:** P3
- **Epic:** EPIC 3 — Market Data
- **Depends on:** QNT-100 (DONE), DEC-023

## Problem
Delistings without cash terms currently resolve at the last traded close (DEC-023) — a
reasonable approximation of acquisition consideration, but an approximation. Actual
transaction terms (cash per share, exchange ratios, mixed consideration) exist in the
historical record and would replace approximation with evidence.

## Objective
A canonical store of acquisition/merger consideration for FTSE-100-ever exits, applied
by the backtest engine in preference to last-close approximation where present.

## Scope
Target schema:

```text
security_id
announcement_date
effective_date
transaction_type          # cash | stock | mixed | scheme_of_arrangement | ...
cash_per_share
cash_currency
stock_exchange_ratio
acquirer_security_id
mixed_consideration       # structured terms where neither pure form fits
source
available_at
confidence
```

- Populate from primary/reliable evidence only (offer documents, RNS, curated histories);
  every record carries provenance; no guessed terms — absence of a record keeps the
  DEC-023 fallback.
- Engine: a consideration record resolves the position at the recorded terms on the
  effective date (stock terms convert at the acquirer's price where the acquirer is in
  the store; otherwise cash-equivalent at announcement is acceptable if labelled).
- `available_at` respects announcement knowledge — a backtest cannot act on terms before
  they were public.
- Start with the largest exits by portfolio impact in the frozen baselines (the events
  where approximation error actually matters), not alphabetically.

## Acceptance criteria
- [ ] Schema + storage with timetravel test (terms unavailable before announcement).
- [ ] Top-impact exits (≥ the ten largest baseline positions ever delisted) covered with
      sourced terms.
- [ ] Baseline delta report: last-close approximation vs actual consideration.
- [ ] DEC entry superseding DEC-023's approximation for covered records; DEC-023 remains
      the documented fallback for uncovered ones.

## Completion notes
_Not started. Momentum research is NOT blocked on this (2026-08-21 directive §5)._
