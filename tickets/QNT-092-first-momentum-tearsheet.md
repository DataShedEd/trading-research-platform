# QNT-092 — First real backtest: 12-1 momentum, FTSE 100, 2010–2026, with tearsheet

- **Ticket ID:** QNT-092
- **Status:** DONE
- **Priority:** P1
- **Epic:** EPIC 8 — Backtesting Engine

## Problem
QNT-050–054 are green on synthetic fixtures, but the platform has not yet produced its first
end-to-end research artefact on real data. Two gaps stand between the engine and an honest run:
(1) the canonical store holds dividends and splits but no delisting/merger actions, so a holding
that leaves the market would remain a stale-marked phantom position forever; (2) nothing loads the
canonical parquet datasets into the engine's `MarketData` or renders a result into a reviewable
tearsheet.

## Objective
Run momentum_12_1 over the survivorship-free FTSE 100, monthly rebalance, top-20 equal weight,
2010-01-01 to the data edge, with pessimistic default costs — and persist the full reproducibility
record plus a markdown tearsheet.

## Scope
- Engine: forced-exit convention for stale holdings (no print for >15 calendar days and no
  delisting record → exit at the last traded close, value-neutral, warned and logged) — DEC-019.
- `src/trp/backtest/runner.py`: load canonical prices/dividends/splits into `MarketData` (with
  dataset versions recorded), build the config, run, `write_run` + metrics + tearsheet.
- Performance: `MarketData.bars_for/actions_for` slices and a context factor-lookback window so
  each rebalance computes factors from ~14 months of member bars rather than the full 18-year
  panel.
- `docs/tearsheets/` output: config, headline metrics, annual returns, costs/turnover, top
  drawdown, caveats (DEC-014 coverage, DEC-016 gaps, DEC-019 exits).

## Acceptance criteria
- [x] A stale holding with no delisting record force-exits at its last close; tested, including
      that the exit is value-neutral and that a knowable delisting record still takes precedence.
- [x] The run completes over real data 2010→data edge and writes the immutable run record
      (config + hash + git commit + daily/events/rebalances parquet + metrics.json).
- [x] Re-running the identical config reproduces identical daily values (determinism on real data).
- [x] The tearsheet states the coverage policy (DEC-014), known gaps (DEC-016), timing/cost
      conventions (DEC-017), and construction rules (DEC-018) alongside the numbers.

## Dependencies
QNT-050–054 (engine chain), QNT-041 (survivorship gate), QNT-091 (canonical ingestion).

## Risks
Interpreting one backtest as evidence: this artefact is an infrastructure proof, not a research
conclusion; RESEARCH_METHODOLOGY rules 3/7 apply before any claim is made.

## Testing requirements
`tests/backtest/test_engine.py` forced-exit cases; timetravel suites still green (the forced exit
uses only on-or-before-day data). The real-data run itself is gated behind data presence like the
QNT-041 gate suite.

## Completion notes
2026-08-18. DEC-019 forced-exit convention implemented in the engine (15-day stale
holdings exit value-neutrally at the last close; a knowable delisting record takes
precedence — both tested). `trp.backtest.runner`: canonical loaders (unit-repaired
source per DEC-020), the default FTSE 100 momentum config, run + metrics + markdown
tearsheet under docs/tearsheets/, never overwritten. Two engine/data bugs found and fixed
along the way, each now regression-tested: (1) out-of-window actions were being
anchor-checked and excluded ~97% of the cross-section; (2) the run surfaced the QNT-093
unit corruption (a fantasy +28% CAGR) — the whole point of raw-mark accounting.
Result over repaired data (infrastructure proof, not a research conclusion): 2010-01-01
to 2026-08-17, monthly top-20 equal-weight momentum_12_1, pessimistic costs: +10.9% CAGR
net of £1.04m modelled costs on £1m initial, vol 19.2%, Sharpe 0.63 (rf=0), max drawdown
-37.8% troughing 2020-03-23 (the actual COVID low), mean one-way turnover 25.9%/month,
4,818 trades, 10 DEC-019 forced exits. Determinism verified: two runs over the real
dataset are bit-identical across daily values, events and rebalance records. Run record:
data/derived/backtests/momentum-12-1-ftse100-monthly-to-2026-08-17.
