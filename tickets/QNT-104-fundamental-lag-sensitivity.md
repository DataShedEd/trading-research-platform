# QNT-104 — Fundamental reporting-lag sensitivity testing

- **Ticket ID:** QNT-104
- **Status:** BACKLOG
- **Priority:** P2
- **Epic:** EPIC 7 — Factor Engine
- **Depends on:** QNT-097 (DONE); complements QNT-103

## Problem
Every UK fundamental availability date is imputed (DEC-007, DEC-024). A factor result
that flips sign or loses its edge when the assumed reporting lag moves by a month is not
a result about markets — it is a result about the imputation choice.

## Objective
The research framework supports re-running any backtest that consumes fundamentals
across a grid of plausible reporting lags, and reports the spread.

## Scope
- Parameterise the DEC-007 lag (annual/interim offsets) as an explicit override on the
  fundamentals as-of choke point (`trp.canonical.fundamentals.queries.fundamentals`),
  default unchanged.
- Diagnostic harness: run the same experiment config at lags of +30/+60/+90/+120/+150
  days and produce a comparison (the lab's `comparison_report` already renders this).
- The purpose is robustness measurement, NOT lag selection: the baseline lag stays
  DEC-007 regardless of which lag scores best, and the harness output labels every
  variant as a lag diagnostic.
- Research reports using imputed fundamentals must prominently disclose the imputed
  basis and the sensitivity spread.

## Acceptance criteria
- [ ] Lag override plumbed through the choke point with a timetravel test (a lag change
      never lets `available_at > as_of` rows through).
- [ ] One-call diagnostic producing the five-lag comparison for a given experiment.
- [ ] Registry integration: lag-diagnostic runs are tagged and never count as new
      evidence variants for lag-selection.
- [ ] HYP-769cd965's conclusion gains the lag-sensitivity spread as recorded context.

## Completion notes
_Not started. Deliberately deferred to the quality/value phase — must not distract from
the momentum validation critical path (2026-08-21 directive §4)._
