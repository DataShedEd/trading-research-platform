# QNT-088 — Order safeguards

- **Ticket ID:** QNT-088
- **Status:** BACKLOG
- **Priority:** P3
- **Epic:** EPIC 16 — Live Trading

## Problem
The costly live-trading errors are rarely subtle strategy mistakes; they are an order for 100,000
shares instead of 1,000, a whole portfolio bought into one name because a weight was expressed as a
percentage in one place and a fraction in another, or a limit price computed from a corrupt quote. A
correct strategy will produce these orders if given corrupt inputs, so the last check before an order
leaves the system cannot be the strategy's own sense of what is reasonable.

## Objective
Enforce hard pre-trade safeguards — maximum order size, maximum resulting portfolio weight, and price
sanity against reference data — that every order must pass before submission, with rejection as the
default outcome.

## Scope
A pre-trade check stage in the execution path: maximum order value and quantity (absolute and as a
share of recent average daily volume), maximum resulting position weight, maximum aggregate turnover
per session, and price sanity comparing any order price and the current quote against recent
canonical reference prices. Configured limits per environment, structured rejection reasons, and
recorded overrides.

## Out of scope
Risk-model-based limits such as VaR budgets; execution algorithms and order slicing; stale-data and
duplicate detection (QNT-089); the audit trail (QNT-090).

## Acceptance criteria
- [ ] Every order passes through the check stage before submission; a test asserts there is no code
      path from strategy output to broker submission that bypasses it.
- [ ] Maximum order value, maximum order size relative to average daily volume, maximum resulting
      position weight and maximum session turnover are enforced, each with an explicit configured
      limit and no default that permits an unlimited order.
- [ ] Price sanity rejects an order whose price or the prevailing quote deviates from recent
      canonical reference prices by more than a configured tolerance, and rejects outright when no
      reference price is available.
- [ ] A failed check rejects the order and records the reason; the check stage fails closed, so an
      error inside a check rejects rather than passes.
- [ ] Overriding a limit requires an explicit action recorded with actor, timestamp, reason and the
      limit overridden, and cannot be done by editing configuration mid-session.

## Technical notes
Limits are per environment and live limits are set deliberately low at first; growing them is a
decision with a record, not a default. Reference prices come from canonical data rather than the
broker's feed, so that a bad quote from the broker cannot validate itself.

Fail-closed applies to the checks themselves: if the average-daily-volume lookup throws, the order is
rejected. A safeguard that opens under error is not a safeguard.

## Dependencies
QNT-087 — the environment separation and kill switch these per-environment limits sit within.

## Risks
Limits calibrated too tightly cause routine rejections and pressure to disable the checks; mitigated
by tuning them in paper first, by making overrides recorded rather than impossible, and by
distinguishing the limits per environment.

## Testing requirements
`tests/execution/test_order_safeguards.py`: each limit enforced at and beyond its boundary, missing
reference price rejection, fail-closed behaviour when a check raises, the bypass-path assertion, and
the recorded-override path.

## Documentation requirements
The safeguard set, default limits per environment, and the override procedure documented in the
live-trading runbook; `docs/ARCHITECTURE.md` execution-boundary section lists the checks.

## Completion notes
_Not started._
