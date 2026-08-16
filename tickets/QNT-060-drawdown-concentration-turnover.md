# QNT-060 — Drawdown, concentration and turnover metrics

- **Ticket ID:** QNT-060
- **Status:** BACKLOG
- **Priority:** P2
- **Epic:** EPIC 9 — Risk Engine

## Problem
Headline return figures hide the things that actually stop a strategy being run: how deep and how
long the losses got, how much of the result came from a handful of positions, and how much trading
was required to achieve it. Each of these is easy to compute slightly differently — peak-to-trough
on daily versus monthly data, one-sided versus two-sided turnover — and the differences are large
enough to change a conclusion.

## Objective
Compute drawdown series and statistics, concentration measures, and turnover for a portfolio, with
one documented convention per metric.

## Scope
`trp.risk`: drawdown series from an equity curve, maximum drawdown with peak/trough/recovery dates
and duration, time under water; concentration as top-N weight and Herfindahl–Hirschman index;
turnover between two portfolio snapshots and annualised turnover over a rebalance schedule.

## Out of scope
Cost modelling from turnover (owned by the backtester's cost assumptions); attribution of drawdown
to factors; risk limits or alerting.

## Acceptance criteria
- [ ] The drawdown series is computed against the running peak of the equity curve and reports
      maximum drawdown with its peak date, trough date, recovery date, and duration in trading days;
      an unrecovered drawdown reports `None` for recovery rather than the last observation.
- [ ] Concentration reports top-N weight for configurable N and HHI on absolute weights, with HHI
      equal to `1/n` for an equally weighted `n`-security portfolio in a test.
- [ ] Turnover is defined as one-sided (sum of absolute weight changes divided by two), documented
      as such, and is 0 for an unchanged portfolio and 1 for a fully replaced portfolio.
- [ ] Metrics are computed at the frequency of the supplied series and the frequency is reported
      with the result; a monthly series is never presented as a daily-resolution drawdown.
- [ ] Known-answer tests cover a hand-built equity curve with two distinct drawdowns.

## Technical notes
Drawdown must be computed on the total-return equity curve net of assumed costs; comparing a gross
curve's drawdown with a net curve's return is the kind of mismatch that flatters results.

Turnover between snapshots uses target weights where the caller supplies them and drifted weights
otherwise; the choice is a parameter, because reporting turnover on drifted weights understates the
trading a rebalance actually caused.

## Dependencies
QNT-058 — supplies portfolio snapshots and weights that concentration and turnover are computed from.

## Risks
Convention drift between this module and any figure quoted elsewhere in the platform; mitigated by
these being the only implementations and by the API returning the convention alongside the number.

## Testing requirements
`tests/risk/test_drawdown.py` and `tests/risk/test_concentration_turnover.py`, including an
unrecovered-drawdown case and a full-replacement turnover case.

## Documentation requirements
Metric definitions and conventions documented in the module docstrings; the drawdown and turnover
definitions referenced from the backtest reporting documentation so a single definition is quoted.

## Completion notes
_Not started._
