# QNT-061 — Historical VaR, expected shortfall, scenario shocks

- **Ticket ID:** QNT-061
- **Status:** BACKLOG
- **Priority:** P2
- **Epic:** EPIC 9 — Risk Engine

## Problem
A single volatility number says nothing about the tail, and parametric VaR on equity portfolios
assumes away exactly the behaviour that matters. What is wanted is a loss estimate grounded in
returns that actually occurred, plus the ability to ask "what happens to this portfolio if the index
falls 15%, or rates move 100bp, or the mining sector halves" without pretending the answer is a
prediction.

## Objective
Provide historical-simulation VaR and expected shortfall over an explicit lookback and horizon, and
a configurable scenario-shock facility that reprices a portfolio under stated market moves.

## Scope
`trp.risk`: historical-simulation VaR and ES at configurable confidence levels using the portfolio's
current weights applied to historical return vectors; scenario definitions (index move, rate move,
sector shock) applied via beta or factor sensitivity; results expressed in both base currency and
percentage terms.

## Out of scope
Parametric or Monte Carlo VaR; option or derivative repricing; regulatory risk measures;
backtesting of the VaR model itself beyond the coverage check below.

## Acceptance criteria
- [ ] VaR and ES are computed by historical simulation over an explicit lookback window and horizon,
      both required arguments, and both returned with the result alongside the number of scenarios
      used.
- [ ] ES is the mean loss beyond the VaR threshold and is always at least as large as VaR in the
      same run; a test asserts this on random and on hand-built return sets.
- [ ] Scenarios are declarative definitions (a named set of shocks) applied through documented
      sensitivities; adding a scenario requires no change to the calculation code.
- [ ] Results state explicitly that current weights are applied to historical returns and that the
      figures are not forecasts; the caveat is part of the returned result object, not only a
      comment.
- [ ] A coverage test on a long historical window shows realised breaches of the 95% one-day VaR
      within a documented tolerance band.

## Technical notes
Historical simulation is chosen over parametric VaR because equity return tails are not normal and a
personal platform gains nothing from a distributional assumption it cannot validate. The lookback
window choice is itself a risk assumption: a two-year window that excludes 2008 and 2020 will say
the portfolio is safe. Make the window explicit and report the worst observation in it.

Scenario sensitivities depend on beta and factor exposures from QNT-058 and QNT-059 and inherit
their estimation error; the result should carry the estimation windows used.

## Dependencies
QNT-059 — supplies the return series, beta and covariance estimates the simulation and shocks rely on.

## Risks
Tail measures invite false precision. A 99% VaR from 250 observations is determined by two or three
data points; mitigated by reporting the scenario count and by requiring the caveat in the result.

## Testing requirements
`tests/risk/test_var_es.py`: known-answer VaR on a small sorted return set, the ES ≥ VaR property,
insufficient-history handling, and a scenario application test with a hand-computed expected loss.

## Documentation requirements
Methodology, window guidance and the "not a forecast" caveat documented in the module docstring and
summarised in `docs/RESEARCH_METHODOLOGY.md` where risk figures are reported in experiments.

## Completion notes
_Not started._
