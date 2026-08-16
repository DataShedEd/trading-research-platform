# QNT-083 — Broker abstraction layer

- **Ticket ID:** QNT-083
- **Status:** BACKLOG
- **Priority:** P3
- **Epic:** EPIC 15 — Paper Trading

## Problem
Broker APIs are idiosyncratic, stateful and awkward, and their concepts leak: partial fills,
unsettled cash, contract identifiers, connection state, asynchronous callbacks. Letting those
concepts reach the strategy code binds the platform to one broker and, worse, mixes execution
concerns into signal generation — at which point it becomes possible for an execution failure to
change a signal, or for a strategy to be "tested" against behaviour only one broker exhibits.

## Objective
Define a broker-agnostic interface covering account, positions, orders, fills, cash and commissions,
with signal generation strictly separated from execution behind it.

## Scope
`trp.execution`: the `Broker` abstract interface (account summary, positions, cash balances, order
submission, order status, fills, commissions, connection lifecycle); the domain types those methods
exchange (order, order status, fill, commission); a simulated in-memory broker implementation for
testing; the explicit boundary between the signal-generating components and anything that submits an
order.

## Out of scope
Any real broker implementation (QNT-084); reconciliation (QNT-085); order and fill persistence
(QNT-086); live-trading safeguards (Epic 16); order routing or execution algorithms.

## Acceptance criteria
- [ ] The `Broker` interface covers account, positions, cash, order submission, order status, fills
      and commissions, with typed domain models and no broker-specific types in any signature.
- [ ] Order state is modelled explicitly, including partially filled, rejected and cancelled, and the
      permitted state transitions are defined and enforced.
- [ ] A simulated broker implements the full interface and is usable in tests without any network
      access, including partial fills, rejections and commission application.
- [ ] No module under signal generation or portfolio construction imports `trp.execution`, asserted by
      an automated import-direction test.
- [ ] Every interface method that can fail declares its failure mode; connection loss is a distinct,
      explicit outcome rather than an exception type leaking from a client library.

## Technical notes
The separation rule is architectural (ARCHITECTURE: "signal generation and order execution stay
separate components with an explicit interface") and is worth enforcing mechanically, because the
first convenient shortcut across it will be an execution component reading a factor score directly.

Model orders as instructions with intent (target weight or target quantity) recorded alongside the
concrete order, so that Epic 16's safeguards and later cost-model calibration can compare intent with
outcome.

## Dependencies
QNT-062 — the unified portfolio representation that broker positions map into.

## Risks
An interface designed around a single broker's semantics is not really an abstraction; mitigated by
designing against the IBKR and at least one other broker's documented model before implementing, and
by the simulated broker forcing the interface to be complete without a real connection.

## Testing requirements
`tests/execution/test_broker_interface.py`: order state-transition matrix including rejected
transitions, simulated broker conformance across the full interface, partial-fill and commission
handling, and the import-direction assertion.

## Documentation requirements
`docs/ARCHITECTURE.md` gains the `trp.execution` package and states the signal/execution separation
rule and its automated enforcement; the order lifecycle documented in `docs/DATA_MODEL.md`.

## Completion notes
_Not started._
