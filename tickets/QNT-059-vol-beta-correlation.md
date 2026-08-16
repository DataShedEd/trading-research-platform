# QNT-059 — Volatility, beta, correlation, covariance

- **Ticket ID:** QNT-059
- **Status:** BACKLOG
- **Priority:** P2
- **Epic:** EPIC 9 — Risk Engine

## Problem
Volatility, beta and correlation are quoted as though they were properties of a security, but they
are properties of an estimator: a window length, a return frequency, an annualisation convention and
a benchmark choice. Estimates computed with undocumented windows are not comparable between
experiments, and a sample covariance matrix over a few hundred securities and a couple of hundred
observations is close to unusable without shrinkage. This ticket makes the estimator explicit
everywhere.

## Objective
Provide historical volatility, benchmark beta, and correlation/covariance matrices as functions that
require their estimation parameters to be stated, return them alongside the estimate, and expose a
shrinkage option for covariance.

## Scope
`trp.risk` estimators over return series: realised volatility (with annualisation), beta and
tracking error versus a stated benchmark, pairwise correlation and covariance matrices, and a
Ledoit–Wolf-style shrinkage estimator for covariance. Explicit minimum-observation handling.

## Out of scope
Multi-factor risk models and factor covariance decomposition; GARCH or other conditional-volatility
models; VaR and expected shortfall (QNT-061); portfolio-level vol targeting (QNT-068).

## Acceptance criteria
- [ ] Every estimator requires an explicit window and return frequency; there is no default window,
      and the parameters used are returned with the estimate.
- [ ] Annualisation uses a documented periods-per-year constant derived from the trading calendar,
      not a hard-coded 252 buried in the calculation.
- [ ] Series with fewer than the required minimum observations return an explicit insufficient-data
      result rather than a number computed from a handful of points.
- [ ] Covariance estimation offers sample and shrinkage variants; the shrunk matrix is positive
      semi-definite for a test case where the sample matrix is singular.
- [ ] Known-answer tests reproduce hand-computed volatility, beta and correlation on a small fixture
      series.

## Technical notes
Returns come from the derived returns layer and are total returns including dividends
(QUANT_PRINCIPLES §3) — beta against a price-return benchmark and a total-return portfolio is a
benchmark mismatch and must not be possible by accident. The benchmark is a required argument.

Note in the module docstring that these estimates are backward-looking and unstable, and that
correlation rises in stress precisely when diversification is relied upon. Downstream tickets
(QNT-068, QNT-070) must not treat a covariance matrix as though it were known.

## Dependencies
QNT-043 — supplies the return series the estimators consume.

## Risks
Estimation error dominates any conclusion drawn from a covariance matrix over a short window; this
is the main route by which an optimiser produces confident nonsense. Mitigated by shrinkage,
minimum-observation gates, and documenting the caveat where it will be read.

## Testing requirements
`tests/risk/test_estimators.py` with known-answer fixtures, insufficient-data cases, and a
positive-semi-definiteness property test on the shrinkage estimator.

## Documentation requirements
Estimator conventions (window, frequency, annualisation, benchmark) documented in the module
docstring and referenced from `docs/RESEARCH_METHODOLOGY.md` where experiments must record them.

## Completion notes
_Not started._
