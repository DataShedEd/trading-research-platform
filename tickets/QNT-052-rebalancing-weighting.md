# QNT-052 — Rebalancing and weighting schemes

- **Ticket ID:** QNT-052
- **Status:** DONE
- **Priority:** P2
- **Epic:** EPIC 8 — Backtesting Engine

## Problem
The gap between a factor score and a portfolio is where a strategy's realism is decided. Rebalancing
daily on a signal that updates monthly manufactures turnover that costs are then charged against;
weighting by score without limits concentrates the portfolio in whichever security has the most
extreme value; and trading at the same close whose price generated the signal is a look-ahead error
that survives every unit test.

## Objective
Implement periodic rebalance rules and the equal, score-proportional, and inverse-volatility
weighting schemes, with position limits and per-rebalance turnover measurement.

## Scope
`src/trp/backtest/rebalance.py` and `weighting.py`: rebalance schedules (monthly, quarterly,
annually, and on a configured trading-day offset within the period); selection rules (top N by
score, top decile, threshold); weighting schemes (equal, score-proportional with a documented
handling of negative scores, inverse realised volatility); position limits (maximum and minimum
weight, maximum number of holdings, optional sector cap); trade generation from current to target
weights; and turnover computed per rebalance as the one-way traded value over portfolio value.

## Out of scope
Portfolio accounting mechanics (QNT-051); transaction costs charged on the generated trades
(QNT-053); performance metrics (QNT-054); optimiser-based portfolio construction.

## Acceptance criteria
- [ ] Rebalance dates follow the configured schedule over the trading calendar, and a rebalance
      falling on a non-trading day moves to the documented adjacent trading day rather than being
      skipped.
- [ ] Signals are computed from data available strictly before the execution price used, and a test
      asserts that trading uses the next available price rather than the close that generated the
      signal.
- [ ] Each weighting scheme produces weights summing to the configured invested proportion, and
      inverse-volatility weighting uses realised volatility from data available at the rebalance
      date only.
- [ ] Position limits are enforced after weighting, with the redistribution rule for capped weight
      documented and tested, including the case where limits cannot all be satisfied.
- [ ] Securities that leave the universe at a rebalance are exited according to a documented rule,
      and securities that delist between rebalances are handled by QNT-051 rather than being held
      as phantom positions.
- [ ] Turnover is reported per rebalance and cumulatively, and matches a hand-computed fixture.

## Technical notes
Score-proportional weighting is undefined for negative scores, which standardised composites produce
routinely. Options are to weight on rank, to shift scores to positive, or to restrict to positive
scores; whichever is chosen must be configuration, not an implicit clamp.

The execution-price convention (signal from close *t*, trade at open or close of *t+1*) is a
material assumption. Default to the pessimistic choice and record it in the run configuration so it
appears in the experiment record.

## Dependencies
QNT-051 — supplies the portfolio ledger the generated trades are applied to.

## Risks
Rebalance frequency, holding count, and limits are all parameters, and tuning them after seeing
results is over-optimisation. Mitigated by capturing them in `BacktestConfig` and by
RESEARCH_METHODOLOGY rule 4 sensitivity reporting.

## Testing requirements
`tests/backtest/test_rebalance.py`, `tests/backtest/test_weighting.py` — schedule generation across
holidays and month ends; each weighting scheme against hand-computed fixtures; negative-score
handling; position-limit redistribution and the infeasible case; universe exit; hand-computed
turnover.

`tests/timetravel/test_rebalancing.py` (marker `timetravel`) — target weights at a rebalance date
must be unchanged when prices and factor inputs dated after that date are added to the fixture,
including the volatility estimate used by inverse-volatility weighting.

## Documentation requirements
Backtest documentation recording the rebalance schedules, weighting schemes, negative-score policy,
position-limit redistribution rule, execution-price convention, and turnover definition.

## Completion notes
2026-08-18. `weighting.py`: deterministic ranking (score desc, id tiebreak); TOP_N /
TOP_DECILE (ceil, minimum one) / THRESHOLD selection with max_holdings truncating the
selection; equal, score-proportional (NegativeScorePolicy RANK/SHIFT/POSITIVE_ONLY, DEC-018)
and inverse-realised-volatility weighting; position limits via iterative pro-rata cap
redistribution + min-weight drop-and-redistribute, infeasible caps raise. `rebalance.py`:
`rebalance_sessions` works in trading sessions (monthly/quarterly/annually + session
offset), so holiday boundaries move forward by construction (tested on May 2021);
`target_shares` (whole-share floor, unpriced names excluded so the diff exits them);
`one_way_turnover` = (buys+sells)/2 over pre-trade value; `factor_strategy` composes
members -> factor scores (status ok only) -> selection -> weighting -> limits -> targets,
entirely through the clock-bound context. `BacktestContext.realised_volatility` (trailing
126-session sample stdev from the SAME adjusted series as returns, >=21 obs). Engine
reports trades/traded_value/turnover per rebalance (persisted in run records). Execution
convention tested end-to-end: sized on the decision session's close, filled at the next
session's close, affordability-clamped. Universe leavers drop out of targets and the diff
sells them; intra-period delistings are QNT-051 ledger events. Sector caps deferred until
sector reference data exists (no source wired yet). Config additions all hash-relevant.
Tests: `tests/backtest/test_weighting.py`, `test_rebalance.py`,
`tests/timetravel/test_rebalancing.py` (targets and the volatility estimate invariant to
future bars and late-announced actions, all three weighting schemes). 687 tests green.
