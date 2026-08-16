# QNT-053 — Transaction costs and slippage

- **Ticket ID:** QNT-053
- **Status:** BACKLOG
- **Priority:** P2
- **Epic:** EPIC 8 — Backtesting Engine

## Problem
Costs are what separate a backtest from a strategy. UK equity trading carries stamp duty of 0.5% on
purchases, a bid-offer spread that widens sharply outside the largest names, and market impact that
grows with position size relative to traded volume. A backtest that ignores or understates them will
rank a high-turnover strategy first precisely because its costs were omitted.

## Objective
Implement a configurable transaction-cost model — commission, spread, UK stamp duty, and a simple
market-impact assumption — charged on every trade, with pessimistic defaults as required by
RESEARCH_METHODOLOGY rule 5.

## Scope
`src/trp/backtest/costs.py`: a `CostModel` configuration and its application to each generated
trade. Components: commission (fixed per trade and/or basis points, with a minimum), half-spread
charged on both sides (constant, per-security, or a documented function of size/liquidity), UK stamp
duty at 0.5% on purchases of UK-incorporated ordinary shares with the documented exemptions (AIM
securities in particular), and a simple market-impact term as a function of order value relative to
recent median daily traded value. Costs are debited through the QNT-051 ledger and reported per
trade, per rebalance, and cumulatively.

## Out of scope
Rebalance and trade generation (QNT-052); performance metrics (QNT-054); order-book or
queue-position modelling; live execution cost measurement.

## Acceptance criteria
- [ ] Every trade is charged commission, half-spread, applicable stamp duty, and market impact, and
      the total appears in the ledger as an explicit cash debit rather than as an adjusted execution
      price with no audit trail.
- [ ] Stamp duty is charged at 0.5% on purchases only, not on sales, with the AIM exemption applied
      by a documented security-level rule and tested for both cases.
- [ ] Cost parameters are part of `BacktestConfig`, defaults are documented as deliberately
      pessimistic, and a test asserts the shipped defaults are not more optimistic than the
      documented floor.
- [ ] Market impact scales with order value relative to recent median daily traded value, computed
      only from data available at the trade date, and its functional form and parameters are
      documented.
- [ ] Per-trade, per-rebalance, and cumulative cost totals are reported, and cumulative costs
      reconcile exactly with the ledger's cash debits.
- [ ] A hand-computed fixture verifies the total cost of a purchase and a sale of the same size,
      demonstrating the asymmetry stamp duty creates.

## Technical notes
Charge costs as explicit cash flows rather than by shading the execution price: the two are
arithmetically similar but only the former lets a result be decomposed into gross return, costs, and
net return, which is what makes "does this survive costs?" answerable.

Spread data is rarely available historically for smaller UK companies. A conservative
liquidity-banded assumption, documented with its source, is more honest than a single small constant
applied to the whole universe.

## Dependencies
QNT-051 — supplies the ledger the cost debits are booked through.

## Risks
Cost assumptions are the easiest place to flatter a strategy, and the flattering choice is often the
most defensible-sounding one. Mitigated by pessimistic defaults, by recording the model in the run
configuration, and by requiring sensitivity to cost assumptions in the experiment record.

## Testing requirements
`tests/backtest/test_costs.py` — hand-computed cost fixtures for purchase and sale; stamp duty
applied and exempted; minimum-commission cases; market impact at small and large order sizes;
reconciliation of reported costs against ledger debits; the defaults-are-pessimistic assertion.

`tests/timetravel/test_costs.py` (marker `timetravel`) — the liquidity input to the market-impact
term must use only volume data available at the trade date; adding later volume data must not change
a historical cost.

## Documentation requirements
`docs/RESEARCH_METHODOLOGY.md` rule 5 cross-referenced to the implemented model and its defaults.
Backtest documentation recording each cost component, its parameters, the stamp-duty exemption rule,
and the market-impact functional form.

## Completion notes
_Not started._
