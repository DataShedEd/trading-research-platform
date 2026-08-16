# QNT-079 — Portfolio, risk and backtest views

- **Ticket ID:** QNT-079
- **Status:** BACKLOG
- **Priority:** P3
- **Epic:** EPIC 13 — Research Terminal

## Problem
Backtest presentation is where research most often stops being honest. A single equity curve against
a well-chosen benchmark, full-sample statistics and no cost annotation is a marketing chart, and it is
the default output of every backtesting tool. `RESEARCH_METHODOLOGY.md` requires sub-period results,
pessimistic costs and a matched benchmark; the view has to show those by construction, not on
request.

## Objective
Build the portfolio, risk and backtest views: current holdings and exposures, the risk dashboard, and
backtest results presented with rolling and sub-period statistics, costs and benchmark shown.

## Scope
A portfolio view (holdings, weights, exposures by sector, country and currency, cash); a risk
dashboard (volatility, beta, drawdown series, concentration, turnover, VaR/ES, scenario results); a
backtest view (equity curve versus benchmark, drawdown chart, rolling return and volatility, per-year
and per-sub-period statistics, turnover and cost summary, holdings over time).

## Out of scope
Order entry or any execution action; editing portfolios; experiment registry browsing beyond linking
to a run; live-trading monitoring, which belongs with Epic 16.

## Acceptance criteria
- [ ] Backtest results display gross and net-of-cost curves together with the cost assumptions used,
      and the benchmark is named with its return basis; a net curve is never shown without its cost
      assumptions.
- [ ] Per-year and per-sub-period statistics are displayed by default alongside full-sample figures,
      not behind an expander or a toggle.
- [ ] The drawdown chart shows the drawdown series with the maximum drawdown, its dates and its
      recovery status labelled from QNT-060 output rather than recomputed in the frontend.
- [ ] The risk dashboard shows every statistic with its estimation window and the portfolio's origin
      tag and valuation timestamp, and a live portfolio is visually distinct from a simulated one.
- [ ] No statistic displayed anywhere in these views is computed in the frontend; a test asserts the
      displayed values equal the API-served values.

## Technical notes
"No statistics computed in the frontend" is the load-bearing rule: a percentage recalculated in a
component is a second implementation that will eventually disagree with the platform, and the chart
will be believed over the code. Formatting only.

Where a backtest run is linked to an experiment record, show the variant count and any
multiple-testing warning next to the headline metrics — the warning is worth least where it is
easiest to skip.

## Dependencies
QNT-076 — the terminal shell, API client and chart foundation.

## Risks
An attractive equity curve is persuasive out of proportion to its evidential value; mitigated by
showing costs, sub-periods and the variant count adjacent to it rather than elsewhere in the
interface.

## Testing requirements
Component tests asserting displayed values match API values without recomputation, that sub-period
statistics render by default, and that the net curve requires cost assumptions; a snapshot test over
a fixture backtest result.

## Documentation requirements
Terminal usage note describing what each view shows and the deliberate absence of frontend
calculation.

## Completion notes
_Not started._
