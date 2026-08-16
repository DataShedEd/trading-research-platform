# QNT-062 — Unified risk interface for simulated and live portfolios

- **Ticket ID:** QNT-062
- **Status:** BACKLOG
- **Priority:** P2
- **Epic:** EPIC 9 — Risk Engine

## Problem
The obvious failure mode for a risk engine is two of them: one that understands backtest output and
one that understands broker positions, drifting apart until the risk you measured in research is not
the risk you are running. Backtest, paper and live portfolios genuinely differ — settled versus
unsettled cash, fractional versus whole shares, pending orders — but those differences belong in the
adapters, not in the risk calculations.

## Objective
Define one portfolio representation that every risk calculation consumes, with adapters constructing
it from backtest state, paper-broker state and live-broker state, so that identical holdings produce
identical risk output regardless of origin.

## Scope
The canonical `Portfolio` snapshot type (positions, quantities, prices and their source, valuation
timestamp, base currency, cash, and an origin tag); adapters from backtest output and from the broker
abstraction; a single `risk_report` entry point returning exposures, risk statistics, drawdown and
concentration, VaR/ES and scenarios for a snapshot.

## Out of scope
The broker adapters themselves (QNT-083, QNT-084); risk limits and pre-trade checks (QNT-088);
presentation of risk output (QNT-075, QNT-079).

## Acceptance criteria
- [ ] A single frozen `Portfolio` type is the only input accepted by every public function in
      `trp.risk`; no risk function takes a broker object or a backtest result directly.
- [ ] Adapters exist for backtest output and for the broker interface, and an equivalence test shows
      that the same holdings routed through both adapters produce byte-identical risk output.
- [ ] Every snapshot carries a valuation timestamp, price source and origin tag, and these appear in
      the risk report so any figure can be traced to the state it was computed from.
- [ ] Ambiguities that differ between origins — pending orders, unsettled cash, missing prices — are
      represented explicitly in the type and cause a loud failure rather than a silent default when
      the adapter cannot resolve them.
- [ ] `make check` passes with `mypy --strict` over the whole `trp.risk` package.

## Technical notes
This ticket is the acceptance gate for Epic 9: the epic is done when exposures, volatility/beta,
drawdown/concentration/turnover, and VaR/ES all run off this one representation. Prefer failing on
an unpriceable position over marking it at cost — a stale price is a silently wrong risk number.

The origin tag is not decorative: live risk reports must be distinguishable from simulated ones in
logs and in the API, and Epic 16 depends on that distinction.

## Dependencies
QNT-058, QNT-059, QNT-060, QNT-061 — the calculations this interface unifies.

## Risks
An overly narrow representation forces adapters to lie (for example by folding unsettled cash into
cash); mitigated by modelling the awkward fields explicitly and by the equivalence test, which will
fail the moment a second risk code path appears.

## Testing requirements
`tests/risk/test_portfolio_interface.py`, including the cross-adapter equivalence test and failure
tests for missing prices and unresolved pending state.

## Documentation requirements
`docs/ARCHITECTURE.md` records the single-portfolio-representation rule for the risk engine; the
`Portfolio` type documented in `docs/DATA_MODEL.md`.

## Completion notes
_Not started._
