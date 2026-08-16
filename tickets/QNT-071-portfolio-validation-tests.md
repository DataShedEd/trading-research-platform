# QNT-071 — Portfolio construction validation suite

- **Ticket ID:** QNT-071
- **Status:** BACKLOG
- **Priority:** P3
- **Epic:** EPIC 11 — Portfolio Construction

## Problem
Portfolio construction bugs do not announce themselves. Weights that sum to 0.997, a sector cap
breached only when two constraints interact, a single-security universe producing a NaN — each
produces plausible-looking output that quietly invalidates every backtest built on it.
Example-based tests catch the cases the author thought of, which are precisely the cases where the
code is already right.

## Objective
Build a property-based validation suite over the whole portfolio construction stack, asserting the
invariants that must hold for any input rather than for chosen inputs.

## Scope
`tests/portfolio/test_properties.py` using Hypothesis: generated universes, factor scores,
volatilities, covariance matrices and constraint sets, run through weighting, targeting, constraints
and optimisation, asserting the shared invariants. Degenerate-input cases as explicit tests.

## Out of scope
Performance benchmarking; testing of the backtester's rebalance logic; provider or data-layer tests.

## Acceptance criteria
- [ ] Property tests assert, over generated inputs, that weights sum to 1 within the documented
      tolerance, that no weight is NaN or infinite, and that supplied constraints are satisfied
      simultaneously by every construction path.
- [ ] Degenerate inputs — empty universe, single security, all-zero scores, all-identical scores,
      zero-volatility security, singular covariance matrix — raise explicitly or return a documented
      value, and never return silent NaNs.
- [ ] Determinism is asserted as a property: identical inputs in any ordering produce identical
      weights.
- [ ] The suite runs within the standard `make check` time budget, with generation limits documented,
      and any failing example found by Hypothesis is added to the repository as a regression case.
- [ ] Every public function in `trp.portfolio` is covered by at least one property.

## Technical notes
Generating valid covariance matrices needs care — draw a random matrix and form `A·Aᵀ` to get a
positive semi-definite one, and generate singular cases deliberately rather than hoping they appear.

The suite is the enforcement mechanism for QNT-069's simultaneous-satisfaction requirement; it should
be able to fail if a later change makes constraint application relax a cap under redistribution.

## Dependencies
QNT-070 — the last construction component the suite must cover.

## Risks
Slow or flaky property tests get skipped in CI, removing the protection entirely; mitigated by
documented generation limits, a fixed Hypothesis profile in CI, and adding discovered failures as
fast deterministic regression tests.

## Testing requirements
This ticket is the testing requirement; it is complete when `make check` runs the suite in CI and the
Hypothesis database of discovered examples is committed.

## Documentation requirements
The invariant list documented in the test module docstring as the specification of what portfolio
construction guarantees; referenced from `docs/ARCHITECTURE.md`.

## Completion notes
_Not started._
