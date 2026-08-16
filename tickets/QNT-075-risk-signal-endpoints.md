# QNT-075 — Risk and signal endpoints

- **Ticket ID:** QNT-075
- **Status:** BACKLOG
- **Priority:** P3
- **Epic:** EPIC 12 — Research API

## Problem
Risk figures and trading signals are the two outputs most likely to be acted on, and the two most
dangerous to serve without context. A volatility number with no estimation window, a VaR with no
lookback, or a signal with no explanation of what drove it invites exactly the kind of unexamined
trust the platform exists to avoid. A signal endpoint also needs to be unambiguous about whether it
describes a simulated portfolio or the live one.

## Objective
Expose portfolio risk metrics and current signals over HTTP, with every number accompanied by the
parameters that produced it and every signal accompanied by an explanation payload.

## Scope
`trp.api` routers for: risk report for a portfolio (exposures, volatility and beta, drawdown,
concentration, turnover, VaR/ES, scenarios) via the QNT-062 interface; scenario evaluation with
caller-supplied shocks; current signals for a universe `as_of` a date, with a factor-decomposition
explanation payload per signal.

## Out of scope
Order placement or any execution action; risk limit configuration (QNT-088); prose generation from
explanation payloads (QNT-081); the terminal's presentation of these (QNT-079).

## Acceptance criteria
- [ ] Risk responses carry the portfolio origin tag, valuation timestamp and price source from
      QNT-062, and every statistic carries the estimation window, frequency and benchmark used.
- [ ] VaR and ES responses include the lookback window, confidence level, horizon, scenario count and
      the "not a forecast" caveat from QNT-061.
- [ ] Signal responses include a structured explanation payload — contributing factors, their scores,
      their versions and their weights in the composite — sufficient to reconstruct the ranking
      arithmetic without further queries.
- [ ] A request for a live portfolio's risk is distinguishable in the response and in the logs from a
      simulated one; the origin is never inferred by the caller.
- [ ] Endpoints remain GET-only apart from scenario evaluation, which, if it must accept a shock body,
      is explicitly documented as computing-only and is asserted to perform no writes.

## Technical notes
The explanation payload is the contract QNT-081 builds prose from: it must contain numbers, not
sentences. If the LLM layer ever needs a figure that is not in this payload, the correct fix is to add
it here rather than to let the language model derive it.

Scenario evaluation is the one place a request body is plausible, since shock sets are structured.
Keep it a separate router with an explicit no-write assertion so the read-only stance stays checkable.

## Dependencies
QNT-072 — the application skeleton; QNT-062 — the unified risk interface these endpoints call.

## Risks
Serving risk figures makes them feel authoritative regardless of their caveats; mitigated by carrying
the parameters and caveats in the payload itself so any consumer, including the terminal and the LLM,
has to receive them.

## Testing requirements
`tests/api/test_risk_signal_endpoints.py`: parameter and caveat fields present, origin-tag
distinction, explanation payload sufficiency (a test recomputes a composite score from the payload
alone and matches the served ranking), and the no-write assertion on scenario evaluation.

## Documentation requirements
OpenAPI descriptions carry the caveats verbatim; the explanation payload schema documented as the
interface QNT-081 depends on.

## Completion notes
_Not started._
