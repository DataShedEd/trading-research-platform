# QNT-115 — FTSE 250 cross-universe holdout replication

- **Ticket ID:** QNT-115
- **Status:** IN_PROGRESS
- **Priority:** P1
- **Epic:** EPIC 10 — Research Experiment Registry
- **Depends on:** QNT-111..114

## Problem
Does the frozen FTSE 100 momentum strategy generalise to the historical FTSE 250
without modification? This is a CROSS-UNIVERSE HOLDOUT REPLICATION — stronger than the
in-sample FTSE 100 result, but NOT a fully independent temporal/geographic test (same
UK market, overlapping regimes). Terminology is part of the deliverable.

## Frozen strategy (immutable for this exercise — recorded before any FTSE 250 result)
- Factor: momentum_12_1 v1, content_hash 8ebf98e2a766cfd3 (12-1 calendar-month
  total-return convention, golden-validated).
- Selection: the literal frozen config rule — selection="top_n", top_n=20 (NOTE: on the
  FTSE 100 this equalled the top quintile; on the FTSE 250 the SAME top_n=20 is the top
  8% — the freeze is the registered config parameter, resolved and recorded here BEFORE
  any results; portfolio concentration is thereby held constant across universes).
- Weighting equal; monthly rebalance; DEC-017/018 execution and construction; costs
  commission 2bps min £5, spread 10bps, stamp 50bps, impact 25bps; whole shares;
  initial cash 100,000,000 GBX; DEC-023 delistings; DEC-019 backstop; returns library
  missing-data policy; reporting metrics as in QNT-110.
- A FTSE 250 behavioural difference is NOT a defect. A genuine defect stops the
  experiment: ticket, generic fix, FTSE 100 canonical re-run preserved, then restart.

## Pre-registered evaluation (committed before any strategy output)
- Primary metric: Information Ratio vs the validated FTSE 250 TR benchmark.
- Interpretation, fixed in advance: IR > 0 directional replication; IR ≥ 0.1 AND
  positive annualised excess return = supportive replication; IR ≤ 0 failed replication.
- Secondary: CAGR, annualised excess, Sharpe, max drawdown, turnover, years beating
  benchmark, contribution concentration, cost sensitivity.

## Sequence (order is load-bearing)
1. Hypothesis registered + committed (this ticket + registry) before any run.
2. Dataset + gates frozen (QNT-111..114).
3. Exactly ONE canonical run; persist; reproduce from manifest; freeze.
4. Conclusion (SUPPORTED / PARTIALLY SUPPORTED / NOT SUPPORTED / INCONCLUSIVE) BEFORE
   diagnostics.
5. Then: full+common-period FTSE100 vs FTSE250 comparison; breadth (§13);
   promotion/demotion boundary (§14, descriptive only); cost diagnostics baseline/2x/3x
   + monetary turnover at £100k/£500k/£1m/£5m (§15).
6. Report with §16 terminology; §17 next-holdout recommendation (not executed).

## Acceptance criteria
- [ ] All 12 completion requirements of the 2026-08-21 holdout directive satisfied.

## Completion notes
_In progress — hypothesis registration first._
