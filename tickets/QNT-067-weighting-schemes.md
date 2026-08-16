# QNT-067 — Weighting schemes library

- **Ticket ID:** QNT-067
- **Status:** BACKLOG
- **Priority:** P3
- **Epic:** EPIC 11 — Portfolio Construction

## Problem
The backtester already turns a ranked security list into weights, and a live portfolio will need to
do the same. If those are two implementations, the portfolio that was tested is not the portfolio
that gets traded — and the divergence will be small, plausible and undetected. Weighting is also
where quiet edge cases live: a factor score of zero, an all-negative score set, a security with no
volatility estimate.

## Objective
Extract weighting schemes — equal, factor-score proportional, inverse-volatility — into pure
functions in a `trp.portfolio` package, used by both the backtester and live construction.

## Scope
`trp.portfolio.weights`: equal weighting, factor-score weighting (with a documented transformation
for negative and zero scores), inverse-volatility weighting; a common signature taking securities
with their inputs and returning weights; refactoring the backtester to call these functions.

## Out of scope
Volatility targeting and risk parity (QNT-068); constraints (QNT-069); optimisation (QNT-070);
rebalance scheduling, which stays with the backtester.

## Acceptance criteria
- [ ] All schemes are pure functions with no I/O and no dependence on global state, sharing one
      signature and returning weights that sum to 1 within a documented tolerance.
- [ ] Factor-score weighting documents and implements one explicit rule for negative and zero scores
      (for example rank- or z-score-based transformation) rather than producing negative weights by
      accident.
- [ ] Inverse-volatility weighting requires an explicit estimation window from QNT-059 and refuses
      to weight a security whose volatility estimate is missing or zero.
- [ ] The backtester calls these functions rather than its own copies, verified by the previous
      weighting code being deleted and backtest regression tests still passing.
- [ ] Degenerate inputs — empty universe, single security, all-identical scores — are handled with
      documented behaviour and covered by tests.

## Technical notes
Pure functions are the point: they are trivially testable, trivially shared, and cannot introduce a
lookahead by reading data themselves. Everything they need is passed in, including the volatility
estimates and the estimation window used to produce them.

Floats are appropriate here (ARCHITECTURE: `Decimal` in canonical stores, floats in derived
analytics); the sum-to-one tolerance is documented rather than asserted exactly.

## Dependencies
QNT-052 — the backtester's portfolio construction step these functions are factored out of.

## Risks
Refactoring a working backtester risks changing historical results; mitigated by regression tests
that compare full backtest output before and after the refactor and require exact equality.

## Testing requirements
`tests/portfolio/test_weights.py`: known-answer tests per scheme, negative and zero score handling,
missing volatility refusal, degenerate inputs, and the backtest regression comparison.

## Documentation requirements
`docs/ARCHITECTURE.md` gains the `trp.portfolio` package; the negative-score transformation rule
documented in the module docstring since it materially affects results.

## Completion notes
_Not started._
