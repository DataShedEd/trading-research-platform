# QNT-086 — Order and fill capture

- **Ticket ID:** QNT-086
- **Status:** BACKLOG
- **Priority:** P3
- **Epic:** EPIC 15 — Paper Trading

## Problem
Backtest cost assumptions are guesses until they are compared with something real. The comparison
needs data that only exists at the moment of trading and is unrecoverable afterwards: the decision
price, the price when the order was submitted, the fill prices and times, the commissions, and the
rejections and cancellations that never became fills. Without capture, transaction-cost assumptions
stay permanently unvalidated, and `RESEARCH_METHODOLOGY.md` rule 5 remains an assertion rather than a
calibrated input.

## Objective
Persist the complete order and fill lifecycle with timestamps, prices and commissions, in a form
suitable for later cost-model calibration and slippage analysis.

## Scope
Persistence of: the order instruction and its intent (target weight or quantity), the decision
timestamp and reference price, submission timestamp, every status transition, every partial and
complete fill with price, quantity, timestamp and commission, and terminal outcomes including
rejection and cancellation with reasons. Storage schema, write path, and a retrieval API for
analysis.

## Out of scope
The cost-model calibration analysis itself (a later experiment, not a ticket here); execution
algorithms; reconciliation (QNT-085); the audit trail for live trading (QNT-090), which is a distinct
tamper-evident concern.

## Acceptance criteria
- [ ] Every order persists its intent, decision timestamp and reference price, submission timestamp,
      all status transitions and all fills with price, quantity, timestamp and commission.
- [ ] Rejected and cancelled orders are persisted with their reason and are retrievable alongside
      filled ones; an unfilled order leaves a record.
- [ ] Implementation shortfall against the decision reference price is computable per order from the
      persisted data alone, demonstrated by a test that computes it for a fixture order.
- [ ] Records are append-only: a correction is a new record referencing the original, and an
      overwrite attempt fails.
- [ ] The capture path cannot silently fail — a persistence failure during trading raises and blocks
      further order submission.

## Technical notes
The decision reference price is the field most often omitted and the one that makes slippage analysis
possible at all: it is the price the signal was generated against, captured before submission, not the
price observed later.

Storage aligns with the QNT-063 decision — orders and fills are transactional state, so they belong in
the same transactional store rather than in Parquet, with analytical extracts derived from it.

## Dependencies
QNT-084 — the broker adapter producing the order and fill events being captured.

## Risks
Capturing after the fact rather than at the moment of the event loses the timestamps that matter;
mitigated by writing on the event path and by treating a persistence failure as a trading halt rather
than a warning.

## Testing requirements
`tests/execution/test_order_capture.py` against the simulated broker: full lifecycle capture including
partial fills, rejection and cancellation records, implementation shortfall computation, append-only
enforcement, and the persistence-failure halt.

## Documentation requirements
Order and fill schema documented in `docs/DATA_MODEL.md`; a note in `docs/RESEARCH_METHODOLOGY.md`
that captured costs are the intended calibration source for backtest cost assumptions.

## Completion notes
_Not started._
