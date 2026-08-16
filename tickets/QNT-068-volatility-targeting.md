# QNT-068 — Volatility targeting and risk parity concepts

- **Ticket ID:** QNT-068
- **Status:** BACKLOG
- **Priority:** P3
- **Epic:** EPIC 11 — Portfolio Construction

## Problem
Sizing a portfolio to a volatility target is one of the few risk controls that demonstrably changes
outcomes, and it is also a reliable way to fool yourself: the target is enforced against an
*estimate* of future volatility built from the recent past, so the portfolio de-risks after a shock
rather than before one, and a naive daily-rescaling implementation trades constantly for no
economic reason. Risk parity has the same character — elegant in principle, driven by covariance
estimation error in practice.

## Objective
Implement portfolio-level volatility targeting and a simple risk-parity weighting scheme, with the
estimation-error caveats documented where they will be read and the trading cost of rebalancing made
visible.

## Scope
`trp.portfolio`: scaling of portfolio gross exposure to a target annualised volatility using an
explicit estimation window, with a rebalance band and maximum leverage; naive (inverse-variance) and
equal-risk-contribution risk parity over a covariance matrix; reporting of realised versus target
volatility over a backtest.

## Out of scope
Constrained optimisation (QNT-069, QNT-070); leverage above a documented cap; conditional volatility
models such as GARCH; intraday or same-day risk scaling.

## Acceptance criteria
- [ ] Volatility targeting takes an explicit target, estimation window and rebalance band, and only
      rescales when the estimate leaves the band — a test shows turnover materially lower with a
      band than without.
- [ ] Gross exposure is capped by an explicit maximum, and the cap is reported as binding whenever it
      is hit rather than silently applied.
- [ ] Equal-risk-contribution weights satisfy the equal-risk-contribution property within a
      documented tolerance on a test covariance matrix, and fall back loudly when the matrix is not
      positive definite.
- [ ] Realised annualised volatility of a targeted backtest is within a documented tolerance of the
      target over the full sample, and the per-year deviation is reported so that regime dependence
      is visible.
- [ ] The estimation-error caveat is present in the module docstring and in the output of any
      function that consumes a covariance matrix.

## Technical notes
Use the shrinkage covariance estimator from QNT-059 by default for risk parity; the sample matrix is
available but should require an explicit opt-in. Volatility targeting inherits the annualisation
convention from the same module rather than defining its own.

Be honest in the docs about what targeting does and does not do: it stabilises volatility, it does
not improve expected return, and it systematically sells after falls. That behaviour is a design
choice, and an experiment using it must record it as such.

## Dependencies
QNT-067 — the weighting functions this scales; QNT-059 — volatility and covariance estimates it
targets against.

## Risks
Volatility targeting can turn a modest drawdown into a permanent de-risking if the window is short
and the band is narrow; mitigated by the band, the cap, and the per-year realised-volatility report
which makes pathological behaviour visible rather than theoretical.

## Testing requirements
`tests/portfolio/test_vol_targeting.py` and `tests/portfolio/test_risk_parity.py`: band-versus-no-band
turnover comparison, cap-binding reporting, the equal-risk-contribution property, and non-positive-definite
matrix handling.

## Documentation requirements
Method, caveats and the sell-after-falls behaviour documented in the module docstring and referenced
from `docs/RESEARCH_METHODOLOGY.md` as a methodological choice that must be recorded in experiments.

## Completion notes
_Not started._
