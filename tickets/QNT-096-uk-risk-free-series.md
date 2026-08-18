# QNT-096 — UK risk-free series for Sharpe/Sortino honesty

- **Ticket ID:** QNT-096
- **Status:** DONE
- **Priority:** P2
- **Epic:** EPIC 8 — Backtesting Engine

## Problem
Every Sharpe and Sortino so far assumes a zero risk-free rate, overstating risk-adjusted
performance — materially so post-2022, with UK short rates above 4%. The metrics machinery
already records its risk-free rate and source as data; what is missing is a real series.

## Objective
Ingest the UK 3-month gilt yield (EODHD UK3M.GBOND, daily from Dec 2009 — matching DEC-014
coverage) raw-first, and have the runner pass each run's window-mean annual rate into the
metrics with the source recorded.

## Scope
`src/trp/backtest/riskfree.py`: raw-first ingestion into `data/canonical/riskfree/`; a
loader returning the daily (date, annual rate) series; a window-mean helper. Runner wires
the mean into full-sample and rolling metrics. The window-mean-constant treatment is a
documented approximation; per-period excess returns are a possible refinement when regime
Sharpe matters.

## Acceptance criteria
- [x] Series ingested with provenance; loader refuses obviously non-rate values (unit
      guard: annual rates between -2% and 20%).
- [x] Runner passes the window mean; metrics.json records the rate and its source string.
- [x] A dated-window mean is validated against hand-picked values from the series.

## Completion notes
2026-08-18. `trp.backtest.riskfree`: UK3M.GBOND ingested raw-first (4,383 daily rows,
2009-12-31 -> today) into data/canonical/riskfree/ with provenance; loader enforces an
annual-rate sanity band (-2%..20%); `window_mean_rate` returns the mean plus a source
string that states the window, the symbol, and that the window-mean constant is an
approximation — all of which lands in metrics.json via risk_free_source. Runner wires it
into full-sample and rolling metrics; the tearsheet Sharpe moved 0.63 -> 0.56 at the
1.37% window mean and now labels its rate. Gate test pins the series to known regimes
(2015 near zero, 2023 at 4-5%). SONIA.MONEY was rejected: EODHD's series is stale
(ends Aug 2023) and short (2018+). 759 default + 9 gate tests green.
