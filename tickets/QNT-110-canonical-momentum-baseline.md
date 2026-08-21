# QNT-110 — Canonical momentum baseline: frozen result, full research report, diagnostics

- **Ticket ID:** QNT-110
- **Status:** IN_PROGRESS
- **Priority:** P1
- **Epic:** EPIC 10 — Experiment Registry
- **Depends on:** QNT-107, QNT-108, QNT-109, QNT-102 (DONE)

## Problem
momentum-baseline (EXP-b99d3f65) exists as the QVM control — completed, reproducible,
never concluded, reported only as a tearsheet. The platform's first canonical
single-factor result deserves the full treatment: frozen baseline, complete research
report, robustness diagnostics (never promoted), concentration analysis, and an honest
verdict on whether the research engine is trustworthy.

## Objective
Answer: "do we possess a trustworthy research engine, and what does the simplest
properly controlled UK momentum experiment actually tell us?"

## Scope
- Baseline = the existing pre-registered momentum-baseline config (PIT FTSE 100,
  2010→2026-08-17, momentum_12_1 v1, monthly, top 20 ≈ quintile, equal weight, ISF
  benchmark, DEC-017 execution, shipped costs). No parameter changes after seeing
  results except documented corrections.
- Registered under a new momentum-premium hypothesis with the honest caveat that the
  control run's results were already visible (in-sample; pre-registration is partial).
- Extended report per directive §12: definition, performance stats (incl. Sortino,
  Calmar, beta), annual table, rolling 12m/3y/5y, drawdown episodes, portfolio
  behaviour (holdings, turnover, concentration, cash drag, delistings, forced exits,
  DEC-016 encounters), data-quality disclosure.
- Inspectable artefacts (§13): factor rankings and holdings history persisted per
  rebalance alongside the existing equity/events/rebalance records + manifest.
- Robustness diagnostics (§15), labelled, never promoted: 6-1, 12-2, 2x costs, top
  decile, quarterly.
- Concentration (§16): contribution by security and year, ex-top-1 and ex-top-5.
- Sanity check (§14) recorded in the conclusion.

## Acceptance criteria
- [ ] Baseline frozen: reproducible run, conclusion recorded with weaknesses (imputed
      DEC-016 missingness, in-sample caveat).
- [ ] Report covers every §12 item; artefacts cover every §13 item.
- [ ] Diagnostics + concentration reported; no unexplained extraordinary performance.
- [ ] Completion verdict delivered (trustworthy / with limitations / not yet).

## Completion notes
_In progress._
