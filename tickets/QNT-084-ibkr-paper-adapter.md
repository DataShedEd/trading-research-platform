# QNT-084 — Interactive Brokers paper adapter

- **Ticket ID:** QNT-084
- **Status:** BACKLOG
- **Priority:** P3
- **Epic:** EPIC 15 — Paper Trading

## Problem
Paper trading is where the gap between backtest assumptions and reality first becomes measurable:
real contract identifiers, real market-data entitlements, real order rejections, real commission
schedules. The IBKR API is also famously stateful and asynchronous, with a connection model and
identifier scheme that will fight any clean interface. Getting that friction absorbed in an adapter —
and discovering the entitlement and data limitations early — is the point of doing paper trading at
all.

## Objective
Implement the QNT-083 `Broker` interface against an Interactive Brokers paper account, with contract
resolution, connection handling and market-data entitlements documented.

## Scope
`trp.execution.ibkr`: connection and session lifecycle, contract resolution from the platform's
`security_id` to IBKR contracts, account and position retrieval, order submission and status,
fill and commission retrieval, error and rejection mapping to the interface's failure modes, and
credentials handled through the QNT-003 settings mechanism.

## Out of scope
Live-account connectivity and its separation (QNT-087); reconciliation (QNT-085); order and fill
persistence (QNT-086); market-data ingestion for research, which stays with the provider layer;
any order type beyond those needed for daily rebalancing.

## Acceptance criteria
- [ ] The adapter implements the full `Broker` interface against a paper account and passes the same
      conformance test suite as the simulated broker, run manually against a live paper connection and
      recorded in the completion notes.
- [ ] Contract resolution maps platform `security_id` to IBKR contracts deterministically, and an
      ambiguous or unresolvable contract raises rather than guessing between candidates.
- [ ] Connection loss and reconnection are handled explicitly, with in-flight order state re-queried
      on reconnect rather than assumed.
- [ ] IBKR errors and rejections are mapped to the interface's declared failure modes, with unmapped
      codes logged with their raw text and surfaced as an explicit unknown-error outcome.
- [ ] Market-data entitlements required for the intended universe are documented, including what is
      unavailable without a subscription and what that prevents.

## Technical notes
Credentials and account identifiers come from settings as secrets (QNT-003) and must never appear in
logs. The paper account identifier should be recorded in configuration in a form that Epic 16's
environment separation can assert against.

Ambiguous contract resolution is a real hazard for UK equities with multiple listings and currencies;
resolve on exchange and currency explicitly rather than accepting the first match, and treat
multiple matches as an error.

## Dependencies
QNT-083 — the broker interface this implements.

## Risks
Test coverage against a real broker is limited by what a paper account will do on demand; mitigated
by running the conformance suite against the paper connection manually and recording the result, and
by keeping broker-specific logic thin enough to inspect.

## Testing requirements
`tests/execution/test_ibkr_adapter.py` with the network boundary mocked for automated runs, plus the
conformance suite executed against a real paper connection as a documented manual step; contract
resolution tests including an ambiguous case.

## Documentation requirements
A paper-trading setup note covering account configuration, required entitlements and their cost, and
known limitations; a `DECISIONS.md` entry for the IBKR client library chosen.

## Completion notes
_Not started._
