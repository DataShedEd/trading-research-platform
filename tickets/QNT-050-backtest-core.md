# QNT-050 — Backtest engine core and PIT data access

- **Ticket ID:** QNT-050
- **Status:** BACKLOG
- **Priority:** P2
- **Epic:** EPIC 8 — Backtesting Engine

## Problem
A backtest is the point where every point-in-time guarantee in the platform is either honoured or
quietly discarded. A vectorised loop over a preloaded price panel is fast and almost impossible to
audit: nothing distinguishes a lookup of yesterday's close from tomorrow's, and a result cannot be
reproduced later because the parameters that produced it were arguments in a notebook cell.

## Objective
Build an event-driven daily backtest loop over an arbitrary historical universe, in which all data
access goes through `as_of` APIs, driven by a run configuration object that captures every parameter
needed to reproduce the run.

## Scope
`src/trp/backtest/` package: `engine.py` (the daily event loop advancing a simulation clock over the
trading calendar, emitting rebalance and market events), `context.py` (the point-in-time data access
facade handed to strategy code, exposing prices, factors, and universe membership only through
`as_of`-bound methods), `config.py` (the frozen `BacktestConfig` — date range, universe and its
version, factor/composite definitions and versions, rebalance rule, weighting, cost model, benchmark,
seed, data versions), and `result.py` (the run record: configuration, git commit, data versions,
positions and cash history, event log).

## Out of scope
Portfolio accounting (QNT-051); rebalancing and weighting schemes (QNT-052); costs (QNT-053);
metrics (QNT-054); the leakage suite (QNT-057); intraday simulation and live execution.

## Acceptance criteria
- [ ] The engine advances day by day over the exchange trading calendar for the configured period,
      skipping non-trading days, and emits rebalance events according to the configured schedule.
- [ ] Strategy code receives only the `as_of`-bound context; a test asserts that requesting data
      dated after the simulation clock raises rather than returning a value.
- [ ] `BacktestConfig` is frozen, fully serialisable, and captures every parameter of a run; a test
      round-trips a configuration and asserts that re-running it reproduces identical results.
- [ ] Each run record persists the configuration, the git commit, the versions of every dataset and
      factor definition used, and the random seed, per QUANT_PRINCIPLES §4.
- [ ] The universe is resolved per rebalance date through the QNT-038 query API, so a run over a
      period in which constituents change reflects those changes rather than a fixed list.
- [ ] Two runs of the same configuration over the same data produce identical results, and a run
      whose configuration differs in any single field produces a distinguishable run record.

## Technical notes
Event-driven and daily by choice: the loop is slower than a vectorised panel computation, but the
simulation clock makes look-ahead a structural impossibility rather than a discipline. Optimise only
if a real run proves too slow, and never by handing strategy code a preloaded future-inclusive
panel.

The context facade is the enforcement point. Bind `as_of` at construction for each simulated day and
give it no method that takes a date the caller chooses, so that "read tomorrow's price" is not
expressible.

## Dependencies
QNT-042 — supplies the versioned factor definitions and their computation surface.
QNT-038 — supplies the point-in-time universe membership the loop iterates over.

## Risks
Performance may become the pressure that erodes the design, with a "just this once" bulk preload
reintroducing leakage. Mitigated by keeping the facade the only data path and by QNT-057's
end-to-end proofs.

## Testing requirements
`tests/backtest/test_engine.py`, `tests/backtest/test_config.py` — calendar advance and holiday
skipping, rebalance scheduling, configuration round-trip and reproducibility, run-record contents.

`tests/timetravel/test_backtest_context.py` (marker `timetravel`) — the context must refuse or
exclude data with a timestamp after the simulation clock, for prices, fundamentals, factors and
universe membership alike; a fixture containing future data must produce results identical to one
where that data is absent.

## Documentation requirements
`docs/ARCHITECTURE.md` updated with the `trp.backtest` package and the context-facade rule.
`docs/RESEARCH_METHODOLOGY.md` cross-reference from the experiment record to `BacktestConfig` as the
reproducibility artefact.

## Completion notes
_Not started._
