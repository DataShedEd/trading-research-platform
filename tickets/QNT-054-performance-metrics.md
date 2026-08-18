# QNT-054 — Performance metrics suite

- **Ticket ID:** QNT-054
- **Status:** DONE
- **Priority:** P2
- **Epic:** EPIC 8 — Backtesting Engine

## Problem
Performance metrics look trivial and are routinely wrong: Sharpe ratios computed without a risk-free
rate, annualised by the wrong factor, or from monthly data compared against a daily figure; maximum
drawdown measured on month-end values that miss the intra-period trough. Every conclusion the
platform reaches rests on these numbers, so an unverified metric quietly corrupts the whole research
record.

## Objective
Implement the core performance metric suite — CAGR, annualised volatility, Sharpe, Sortino, maximum
drawdown, Calmar, beta, turnover, hit rate, and annual returns — each validated against
hand-computed fixtures.

## Scope
`src/trp/backtest/metrics.py` computing metrics from a backtest's equity curve, return series, and
trade log; explicit conventions for the risk-free rate source, the annualisation factor, the
periodicity of the input series, and the definition of hit rate (proportion of positive periods and,
separately, proportion of profitable positions); a metrics record persisted with each run result.

## Out of scope
Benchmark-relative metrics (QNT-055); rolling statistics (QNT-056); statistical significance testing
and multiple-hypothesis adjustment; risk-model attribution.

## Acceptance criteria
- [ ] Each of the ten metrics is implemented and validated against a hand-computed fixture whose
      expected values are derived independently of the implementation.
- [ ] The risk-free rate source, annualisation factor, and input periodicity are explicit parameters
      recorded with the metrics rather than constants inside the functions.
- [ ] Maximum drawdown is computed on the full-frequency equity curve, and a test with a
      within-month trough asserts it is not understated by month-end sampling.
- [ ] Sortino uses a documented downside-deviation definition with a stated minimum acceptable
      return, and Calmar uses the same period as the drawdown it divides by.
- [ ] Degenerate inputs are handled explicitly: a series shorter than one year, a constant equity
      curve (zero volatility), and an all-negative series each return a documented result rather
      than a division error or a misleading number.
- [ ] Beta is computed against a supplied series with the same periodicity and overlapping dates
      only, and a test asserts that mismatched or partially overlapping series raise rather than
      silently aligning by position.

## Technical notes
Compute everything from one canonical daily return series derived from the equity curve, and
aggregate to other frequencies from there, so no two metrics can disagree about what the returns
were.

CAGR from a period shorter than a year is an extrapolation and should be flagged as such rather than
reported plainly; the same applies to a Sharpe ratio computed on a handful of observations.

## Dependencies
QNT-051 — supplies the portfolio equity curve, cash flows, and trade log the metrics are computed
from.

## Risks
Metrics computed on short or regime-specific samples invite over-reading; RESEARCH_METHODOLOGY rule
7 requires sub-period reporting, so annual returns are part of this suite rather than an optional
extra. Mitigated by flagging short-sample results in the metrics record.

## Testing requirements
`tests/backtest/test_metrics.py` — hand-computed fixtures for every metric; the within-month
drawdown case; zero-volatility, short-series and all-negative degenerate cases; periodicity and
alignment mismatch rejection; consistency between annual returns and full-period CAGR.

No new historical data access is introduced here, so no time-travel test is required; the metrics
are, however, exercised end-to-end within the QNT-057 suite.

## Documentation requirements
Backtest documentation recording each metric's formula, annualisation convention, risk-free rate
source, hit-rate definitions, and degenerate-input behaviour.

## Completion notes
2026-08-18. `metrics.py`: everything derives from ONE canonical daily simple-return series
(`daily_returns`, which refuses unsorted or malformed curves), so no two metrics can
disagree about the returns. Ten metrics in a frozen `MetricsRecord` that also carries its
conventions as data: periods_per_year (annualisation), annual risk-free rate + source text
(geometrically de-annualised), Sortino MAR (defaults to rf, recorded), flags. Hand-computed
fixture (+10/-10/+10/0/+20 with periods_per_year=5) pins CAGR/vol/Sharpe (1.17669681)/
Sortino (exactly 3.0)/max drawdown/Calmar/hit rate to paper-derived values. Max drawdown
runs on the FULL-frequency curve with the trough date reported; the month-end
understatement case is tested explicitly. Degenerates: <1yr flags annualised figures as
extrapolations (still reported), zero volatility -> Sharpe/Sortino None + flag, all-negative
paths report honest negative CAGR/Calmar, equity-to-zero flags total_loss. Beta demands
identical date sets and same periodicity — partial overlap raises, zero-variance benchmark
raises. Hit rate reported under BOTH definitions: positive periods, and profitable
round-trip positions replayed from the ledger event log (dividends and delisting proceeds
inside the cycle count; still-open positions excluded). Annual returns compound exactly to
total return (tested). `write_metrics` joins the immutable run record (never overwrites).
Tests: `tests/backtest/test_metrics.py` (16). 716 tests green.
