# QNT-108 — Synthetic-market backtest gate: hand-calculated ledger

- **Ticket ID:** QNT-108
- **Status:** IN_PROGRESS
- **Priority:** P1
- **Epic:** EPIC 8 — Backtesting Engine
- **Depends on:** QNT-050…057 (DONE)

## Problem
Scenario tests exercise dividends, consolidations, delistings and cost reconciliation
separately, but no single deterministic market exists where the ENTIRE run — every
selection, fill, dividend, split, delisting, cost and the final portfolio value — was
computed independently by hand and persisted as the expected ledger.

## Objective
A tiny synthetic market (~5 securities, known prices, a dividend, a split, a delisting,
known rebalance dates, known costs) with a hand-derived expected ledger and final value,
asserted exactly (documented tolerances) as a permanent correctness gate.

## Scope
- Deterministic price paths chosen so signal ranking, selection and whole-share
  arithmetic are hand-checkable; strategy = existing top-N factor construction.
- Validate: signal timing (DEC-017 previous-session knowledge), selection, equal
  weighting, whole shares, cash, buys, sells, dividend crediting, split handling,
  delisting resolution (DEC-023), rebalance timing, commission/spread/stamp/impact
  costs, turnover, final value.
- Expected ledger persisted as a fixture with the hand derivation documented alongside;
  engine output compared event-by-event and to the final value.

## Acceptance criteria
- [ ] Expected ledger derived outside the engine (documented arithmetic), persisted.
- [ ] Engine reproduces it exactly (Decimal fields) / within stated tolerance (floats).
- [ ] Runs in the default suite permanently.

## Completion notes
_In progress._
