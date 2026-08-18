# QNT-056 — Rolling statistics

- **Ticket ID:** QNT-056
- **Status:** DONE
- **Priority:** P2
- **Epic:** EPIC 8 — Backtesting Engine

## Problem
A single full-sample Sharpe ratio hides everything that matters about when a strategy worked. A
result driven entirely by 2009-2014 and flat since presents identically to a steadily performing one
at full-sample resolution, and RESEARCH_METHODOLOGY rule 7 requires regime dependence to be visible
rather than inferred.

## Objective
Compute rolling returns, volatility, Sharpe ratio and beta over configurable windows, so that regime
dependence is a reported output of every backtest rather than something a reader has to reconstruct.

## Scope
`src/trp/backtest/rolling.py`: rolling windows specified in trading days or calendar months;
rolling total return, annualised volatility, Sharpe ratio, and beta against a benchmark series; a
minimum-observations requirement per window; and persistence of the resulting series with the run
result so they can be reported and plotted later.

## Out of scope
Full-sample metrics (QNT-054); benchmark construction (QNT-055); charting and reporting, which
belong to the reporting epic; statistical regime detection or change-point analysis.

## Acceptance criteria
- [ ] Rolling return, volatility, Sharpe and beta are computed over configurable window lengths and
      validated against hand-computed fixtures at the window boundaries.
- [ ] Windows are strictly backward-looking: the value at date *t* uses observations at or before
      *t* only, asserted by a test that would fail for a centred window.
- [ ] A minimum-observations requirement is enforced, and windows below it yield a documented
      missing result rather than a statistic computed from a partial window.
- [ ] Window specification supports both trading-day and calendar-month lengths, and the two produce
      consistent results on a fixture where they coincide.
- [ ] Rolling series are persisted with the run result, tagged with their window specification and
      the annualisation convention used.

## Technical notes
Reuse the metric implementations from QNT-054 over each window rather than reimplementing them, so
a rolling Sharpe and the full-sample Sharpe cannot diverge in convention.

Rolling beta needs the same benchmark alignment rules as QNT-055; misaligned dates in a rolling
context produce plausible values that are quietly wrong, so alignment should raise rather than
adapt.

## Dependencies
QNT-054 — supplies the metric implementations and return series the rolling versions apply over.

## Risks
Rolling windows are an obvious place to search for a flattering period. Mitigated by requiring the
full set of windows configured for a run to be reported together, so a selected window is visibly a
selection.

## Testing requirements
`tests/backtest/test_rolling.py` — hand-computed fixtures at window start, middle and end;
backward-looking assertion; minimum-observations behaviour; trading-day versus calendar-month
equivalence; rolling-versus-full-sample consistency where the window covers the whole period.

No new historical data access is introduced here, so no time-travel test is required beyond the
end-to-end coverage in QNT-057.

## Documentation requirements
Backtest documentation recording the window specification format, the backward-looking convention,
the minimum-observations rule, and the annualisation conventions inherited from QNT-054.

# QNT-056 — Rolling statistics

- **Ticket ID:** QNT-056
- **Status:** DONE
- **Priority:** P2
- **Epic:** EPIC 8 — Backtesting Engine

## Problem
A single full-sample Sharpe ratio hides everything that matters about when a strategy worked. A
result driven entirely by 2009-2014 and flat since presents identically to a steadily performing one
at full-sample resolution, and RESEARCH_METHODOLOGY rule 7 requires regime dependence to be visible
rather than inferred.

## Objective
Compute rolling returns, volatility, Sharpe ratio and beta over configurable windows, so that regime
dependence is a reported output of every backtest rather than something a reader has to reconstruct.

## Scope
`src/trp/backtest/rolling.py`: rolling windows specified in trading days or calendar months;
rolling total return, annualised volatility, Sharpe ratio, and beta against a benchmark series; a
minimum-observations requirement per window; and persistence of the resulting series with the run
result so they can be reported and plotted later.

## Out of scope
Full-sample metrics (QNT-054); benchmark construction (QNT-055); charting and reporting, which
belong to the reporting epic; statistical regime detection or change-point analysis.

## Acceptance criteria
- [ ] Rolling return, volatility, Sharpe and beta are computed over configurable window lengths and
      validated against hand-computed fixtures at the window boundaries.
- [ ] Windows are strictly backward-looking: the value at date *t* uses observations at or before
      *t* only, asserted by a test that would fail for a centred window.
- [ ] A minimum-observations requirement is enforced, and windows below it yield a documented
      missing result rather than a statistic computed from a partial window.
- [ ] Window specification supports both trading-day and calendar-month lengths, and the two produce
      consistent results on a fixture where they coincide.
- [ ] Rolling series are persisted with the run result, tagged with their window specification and
      the annualisation convention used.

## Technical notes
Reuse the metric implementations from QNT-054 over each window rather than reimplementing them, so
a rolling Sharpe and the full-sample Sharpe cannot diverge in convention.

Rolling beta needs the same benchmark alignment rules as QNT-055; misaligned dates in a rolling
context produce plausible values that are quietly wrong, so alignment should raise rather than
adapt.

## Dependencies
QNT-054 — supplies the metric implementations and return series the rolling versions apply over.

## Risks
Rolling windows are an obvious place to search for a flattering period. Mitigated by requiring the
full set of windows configured for a run to be reported together, so a selected window is visibly a
selection.

## Testing requirements
`tests/backtest/test_rolling.py` — hand-computed fixtures at window start, middle and end;
backward-looking assertion; minimum-observations behaviour; trading-day versus calendar-month
equivalence; rolling-versus-full-sample consistency where the window covers the whole period.

No new historical data access is introduced here, so no time-travel test is required beyond the
end-to-end coverage in QNT-057.

## Documentation requirements
Backtest documentation recording the window specification format, the backward-looking convention,
the minimum-observations rule, and the annualisation conventions inherited from QNT-054.

## Completion notes
2026-08-18. `trp.backtest.rolling`: RollingSpec (exactly one of trading_days /
calendar_months, min_observations >= 2), strictly backward-looking windows (tested by
appending future observations), metric formulas ARE the QNT-054 implementations
(compound/annualised_volatility/sharpe_ratio extracted as the single shared versions, so
rolling and full-sample cannot diverge — whole-period-window equality tested), rolling
beta requires exact benchmark alignment and raises otherwise. Windows below
min_observations yield nulls, never partial statistics; the first real tearsheet
exposed why the minimum must scale with the window (a "36m" Sharpe of -5.33 from 20
early observations) — runner windows now require ~80% of expected sessions.
Trading-day and calendar-month specs agree where they coincide (tested).
`rolling_report` emits ALL configured windows in one frame, persisted as
rolling.parquet in every run record; the tearsheet reports worst/median/best per window
together. Real run: worst 12m -25.6% (to the COVID low), 12m Sharpe range -1.18..3.60.
746 tests green.

