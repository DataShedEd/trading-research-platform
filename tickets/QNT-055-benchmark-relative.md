# QNT-055 — Benchmark and relative performance

- **Ticket ID:** QNT-055
- **Status:** DONE
- **Priority:** P2
- **Epic:** EPIC 8 — Backtesting Engine

## Problem
Absolute returns say little on their own. Comparing a UK mid-cap strategy against a price-only index,
against a large-cap index, or against a benchmark in a different currency produces an excess return
that measures the mismatch rather than the strategy — and the mismatch usually favours the strategy,
because a price index omits dividends worth several percent a year.

## Objective
Provide total-return benchmark series and the relative performance measures built on them — excess
returns, tracking error, and information ratio — with an automated check that the benchmark matches
the strategy universe as required by RESEARCH_METHODOLOGY rule 6.

## Scope
`src/trp/backtest/benchmark.py`: ingestion or construction of total-return benchmark series for the
platform's universes (FTSE 100, FTSE 250, FTSE 350 and, where an external series is unavailable, a
constructed capitalisation-weighted total-return series over the corresponding historical universe);
excess return, tracking error, and information ratio calculations; and a benchmark-suitability check
comparing the configured benchmark against the strategy universe, currency, and date coverage.

## Out of scope
Absolute performance metrics (QNT-054); rolling statistics (QNT-056); risk-model factor attribution;
peer-group or fund comparison.

## Acceptance criteria
- [ ] Benchmark series are total return, not price only, and each series records its source,
      currency, and coverage range; a test asserts a known dividend period produces a total return
      exceeding the price return.
- [ ] Excess return, tracking error, and information ratio are computed against the benchmark on
      matched dates and periodicity, and validated against hand-computed fixtures.
- [ ] A benchmark-suitability check runs with every backtest and fails, or emits a recorded warning
      that appears in the run result, when the benchmark's universe, currency, or coverage does not
      match the strategy's.
- [ ] Where a benchmark is constructed rather than sourced, its construction rules and their
      limitations are documented, and it is labelled as constructed everywhere it is reported.
- [ ] Date alignment is explicit: benchmark observations missing for a strategy trading day raise or
      are handled by a documented rule, never dropped silently from one side of the comparison.
- [ ] Relative metrics appear in the persisted run result alongside the absolute metrics.

## Technical notes
Constructing a capitalisation-weighted total-return series over our own historical universe is a
useful fallback when licensed index series are unavailable, but it is a different object from the
published index and will not reconcile to it. Labelling matters more than accuracy here.

The suitability check is deliberately mechanical — universe name, currency, and coverage overlap —
because the realistic failure mode is inattention, not disagreement about what a fair benchmark is.

## Dependencies
QNT-054 — supplies the return series and metric machinery the relative measures extend.

## Risks
A constructed benchmark built from the same universe as the strategy will share any survivorship or
coverage defect in that universe, making relative performance look artificially clean. Mitigated by
recording the shared provenance in the run result and stating the limitation in the documentation.

## Testing requirements
`tests/backtest/test_benchmark.py` — total versus price return on a dividend fixture; hand-computed
excess return, tracking error and information ratio; suitability check passing and failing cases;
missing-observation alignment behaviour.

`tests/timetravel/test_benchmark.py` (marker `timetravel`) — a constructed benchmark's value at date
*t* must use only constituents and prices available at *t*, and must be unchanged by later index
revisions or backfilled data.

## Documentation requirements
`docs/RESEARCH_METHODOLOGY.md` rule 6 cross-referenced to the suitability check. Backtest
documentation recording each available benchmark, its source or construction rules, currency, and
coverage.

# QNT-055 — Benchmark and relative performance

- **Ticket ID:** QNT-055
- **Status:** DONE
- **Priority:** P2
- **Epic:** EPIC 8 — Backtesting Engine

## Problem
Absolute returns say little on their own. Comparing a UK mid-cap strategy against a price-only index,
against a large-cap index, or against a benchmark in a different currency produces an excess return
that measures the mismatch rather than the strategy — and the mismatch usually favours the strategy,
because a price index omits dividends worth several percent a year.

## Objective
Provide total-return benchmark series and the relative performance measures built on them — excess
returns, tracking error, and information ratio — with an automated check that the benchmark matches
the strategy universe as required by RESEARCH_METHODOLOGY rule 6.

## Scope
`src/trp/backtest/benchmark.py`: ingestion or construction of total-return benchmark series for the
platform's universes (FTSE 100, FTSE 250, FTSE 350 and, where an external series is unavailable, a
constructed capitalisation-weighted total-return series over the corresponding historical universe);
excess return, tracking error, and information ratio calculations; and a benchmark-suitability check
comparing the configured benchmark against the strategy universe, currency, and date coverage.

## Out of scope
Absolute performance metrics (QNT-054); rolling statistics (QNT-056); risk-model factor attribution;
peer-group or fund comparison.

## Acceptance criteria
- [ ] Benchmark series are total return, not price only, and each series records its source,
      currency, and coverage range; a test asserts a known dividend period produces a total return
      exceeding the price return.
- [ ] Excess return, tracking error, and information ratio are computed against the benchmark on
      matched dates and periodicity, and validated against hand-computed fixtures.
- [ ] A benchmark-suitability check runs with every backtest and fails, or emits a recorded warning
      that appears in the run result, when the benchmark's universe, currency, or coverage does not
      match the strategy's.
- [ ] Where a benchmark is constructed rather than sourced, its construction rules and their
      limitations are documented, and it is labelled as constructed everywhere it is reported.
- [ ] Date alignment is explicit: benchmark observations missing for a strategy trading day raise or
      are handled by a documented rule, never dropped silently from one side of the comparison.
- [ ] Relative metrics appear in the persisted run result alongside the absolute metrics.

## Technical notes
Constructing a capitalisation-weighted total-return series over our own historical universe is a
useful fallback when licensed index series are unavailable, but it is a different object from the
published index and will not reconcile to it. Labelling matters more than accuracy here.

The suitability check is deliberately mechanical — universe name, currency, and coverage overlap —
because the realistic failure mode is inattention, not disagreement about what a fair benchmark is.

## Dependencies
QNT-054 — supplies the return series and metric machinery the relative measures extend.

## Risks
A constructed benchmark built from the same universe as the strategy will share any survivorship or
coverage defect in that universe, making relative performance look artificially clean. Mitigated by
recording the shared provenance in the run result and stating the limitation in the documentation.

## Testing requirements
`tests/backtest/test_benchmark.py` — total versus price return on a dividend fixture; hand-computed
excess return, tracking error and information ratio; suitability check passing and failing cases;
missing-observation alignment behaviour.

`tests/timetravel/test_benchmark.py` (marker `timetravel`) — a constructed benchmark's value at date
*t* must use only constituents and prices available at *t*, and must be unchanged by later index
revisions or backfilled data.

## Documentation requirements
`docs/RESEARCH_METHODOLOGY.md` rule 6 cross-referenced to the suitability check. Backtest
documentation recording each available benchmark, its source or construction rules, currency, and
coverage.

## Completion notes
2026-08-18. `trp.backtest.benchmark` (DEC-021): ISF.LSE + reinvested dividends as the
sourced FTSE 100 total-return benchmark (May 2000 ->), CUKX.LSE accumulating class as
cross-check; both ingested raw-first via the existing EODHD machinery into
data/canonical/benchmarks/ with provenance. `total_return_series` is point-in-time
(dividends filtered by available_at; later bars cannot change earlier values — timetravel
suite) and refuses ~100x unit flips rather than printing a 99% "return". Relative
measures on strictly matched dates (mismatch raises; `align()` is the one documented
reconciliation and RETURNS its drops, which the runner records as a warning):
excess CAGR (geometric), tracking error, information ratio — hand-computed fixtures.
`check_suitability` (universe/currency/coverage) runs with every benchmarked backtest;
findings land in the persisted run warnings. Gate suite: implied reinvested yield in
FTSE territory, and the construction tracks CUKX within 3bp/yr on the 2016+ overlap with
zero dropped sessions (early CUKX thinness is why the check starts 2016). Run records
gain relative.json; the tearsheet gains the benchmark section. Real run: benchmark CAGR
+7.84%, strategy excess +2.86%/yr, TE 12.2%, IR 0.28. 746 tests green.

