# QNT-108 — Synthetic-market backtest gate: hand-calculated ledger

- **Ticket ID:** QNT-108
- **Status:** DONE
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
- [x] Expected ledger derived outside the engine (documented arithmetic), persisted.
- [x] Engine reproduces it exactly (Decimal fields) / within stated tolerance (floats).
- [x] Runs in the default suite permanently.

## Completion notes
`tests/backtest/test_synthetic_market_gate.py` + `golden/synthetic_market_ledger.json`.
Five securities on the real XLON calendar, Jan–Apr 2021, driven by the REAL
factor_strategy over the registered momentum_3_0 definition (top 2, equal weight,
10 bps commission). The scenario exercises, in one connected run: DEC-017 signal timing
(every step in a price path lands mid-month so decision sizing price == fill price by
construction, and momentum windows shift visibly between decisions), selection changes,
whole-share flooring, affordable-cash shrinking of buys, sells-before-buys ordering, a
dividend on a held name (also flowing into that name's total-return momentum), a 2-for-1
split on a held name (position doubles, value unmoved, split-adjusted momentum), a
FAILURE delisting of a held name (booked as KNOWN zero proceeds, cash_delta exactly 0),
turnover and per-rebalance costs, and the final value.

Every number in the fixture was derived by hand in the module docstring before the
engine ran; the derivation includes the affordable-shrink arithmetic
(int(shares x cash / total)) per squeezed buy. Two of my hand-model errors were caught
by the engine on first run and corrected in the fixture with adjudication notes: (1) a
known FAILURE books delisting_proceeds@0, not the unknown-terms write-off; (2) the
Mar 1 position count is 2 (s1 had exited) — value and cash matched to the penny
throughout, on first run. Tolerances: counts/kinds/dates exact, money 1e-6 abs (exact
decimals through float), turnover 1e-9 rel. Runs in the default suite (no data/
dependency), permanently.
