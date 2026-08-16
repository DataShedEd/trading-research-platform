# QNT-070 — Optimisation with stability controls

- **Ticket ID:** QNT-070
- **Status:** BACKLOG
- **Priority:** P3
- **Epic:** EPIC 11 — Portfolio Construction

## Problem
Mean-variance optimisation is the most reliable way to produce a portfolio that looks excellent in
sample and behaves badly out of it. Given noisy expected returns and an ill-conditioned sample
covariance matrix, the optimiser does exactly what it is asked: it concentrates the portfolio in
whichever securities the estimation error happened to flatter, and it produces wildly different
weights from tiny input changes. The brief warns about optimisation for this reason. If it is
implemented at all, it must be implemented defensively and held to a higher evidential standard than
the simple schemes.

## Objective
Provide cautious mean-variance and minimum-variance optimisation with covariance shrinkage,
mandatory weight bounds, and stability diagnostics that make estimation-error sensitivity visible
rather than hidden.

## Scope
`trp.portfolio.optimise`: minimum-variance and mean-variance objectives over a shrunk covariance
matrix, subject to QNT-069 constraints as hard bounds; a required maximum position bound; stability
diagnostics reporting weight change under input perturbation and the condition number of the
covariance matrix used.

## Out of scope
Black–Litterman and other return-forecast frameworks; transaction-cost-aware multi-period
optimisation; non-convex objectives; any optimiser used as the platform default.

## Acceptance criteria
- [ ] Optimisation requires a shrunk covariance estimator and explicit per-position bounds; calling
      it with the sample covariance matrix or with unbounded weights raises rather than warning.
- [ ] The solution satisfies all supplied QNT-069 constraints exactly, verified by re-running the
      constraint checker on the optimiser output.
- [ ] A stability diagnostic perturbs expected-return inputs by a documented amount and reports the
      resulting mean absolute weight change; the diagnostic is returned with every optimisation
      result, not available on request.
- [ ] Minimum-variance results are compared against equal-weight and inverse-volatility baselines in
      a documented test, and the comparison is included in the module documentation so the
      complexity cost is stated with evidence.
- [ ] Infeasible or non-converged problems raise with the solver status; no fallback to an
      unconstrained or heuristic solution.

## Technical notes
Minimum variance is preferred to full mean-variance because it needs no expected-return input, and
expected returns are the noisiest input in the problem. Where mean-variance is used, the expected
returns must come from a versioned factor definition and be recorded in the experiment record.

An experiment using an optimiser should be held to `RESEARCH_METHODOLOGY.md` rule 4 with particular
severity: report the parameter sensitivity, and prefer the simpler scheme when the optimiser's
advantage is within the noise.

## Dependencies
QNT-069 — the constraint framework the optimiser must satisfy.

## Risks
This ticket adds the platform's most overfitting-prone component. Mitigated by mandatory shrinkage
and bounds, by the always-on stability diagnostic, and by documenting the baseline comparison so the
optimiser has to earn its place rather than being assumed superior.

## Testing requirements
`tests/portfolio/test_optimise.py`: constraint satisfaction on optimiser output, refusal of sample
covariance and unbounded weights, a known-answer minimum-variance solution on a small analytic case,
the perturbation diagnostic, and non-convergence handling.

## Documentation requirements
Module docstring stating the overfitting warning, the shrinkage and bounds requirements, and the
baseline comparison result. A `DECISIONS.md` entry if an optimisation library dependency is added.

## Completion notes
_Not started._
