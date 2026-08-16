# QNT-085 — Position and cash reconciliation

- **Ticket ID:** QNT-085
- **Status:** BACKLOG
- **Priority:** P3
- **Epic:** EPIC 15 — Paper Trading

## Problem
Internal state and broker state drift. A fill arrives while the process is down, a corporate action
is applied by the broker and not by the platform, a partial fill is recorded twice, a dividend lands
in cash. Every one of these is small, and every one makes the platform's idea of the portfolio — the
one risk is computed from and the next rebalance is calculated against — quietly wrong. The dangerous
response is auto-correction: silently adopting broker state hides the bug that caused the divergence
and can mask a genuinely serious problem.

## Objective
Reconcile internal positions and cash against broker state on a schedule, reporting every discrepancy
loudly and never correcting one silently.

## Scope
`trp.execution.reconcile`: a daily reconciliation comparing internal positions, quantities, cash
balances and commissions against the broker's account state; classification of discrepancies by type
and materiality; persisted reconciliation reports; alarms on any unexplained discrepancy; an explicit,
logged operator action for accepting a broker figure.

## Out of scope
Automatic remediation of any kind; corporate-action processing itself; live-account specifics
(Epic 16); order and fill capture (QNT-086).

## Acceptance criteria
- [ ] Reconciliation compares positions (by security and quantity), cash by currency, and cumulative
      commissions, and produces a persisted report for every run, including clean runs.
- [ ] Any discrepancy raises an alarm through the logging and alerting path and marks the portfolio
      state as unreconciled; no discrepancy is auto-corrected.
- [ ] Trading is blocked while the portfolio is unreconciled, asserted by a test that attempts an
      order after an unresolved discrepancy.
- [ ] Accepting a broker figure requires an explicit operator action that is recorded with a reason,
      a timestamp and the before/after values.
- [ ] Reconciliation runs on a schedule and a missed run is itself an alarm rather than silence.

## Technical notes
"Blocked while unreconciled" is the safety property that makes the rest meaningful: an alarm nobody
acts on is a log line, while a halt is a decision. The block belongs here rather than in Epic 16
because paper trading is where the failure modes should be discovered.

Expect a class of benign discrepancies (rounding on commissions, timing of dividend credit). Classify
them, do not suppress them: a classification with a documented tolerance is auditable, whereas a
filter that hides small differences will eventually hide a large one built from small ones.

## Dependencies
QNT-084 — the broker adapter supplying the external state to reconcile against.

## Risks
Frequent benign alarms cause the alarm to be ignored — the real failure mode of any reconciliation
system. Mitigated by explicit classification with documented tolerances and by tracking alarm volume
so desensitisation is visible.

## Testing requirements
`tests/execution/test_reconciliation.py` against the simulated broker: clean run, quantity mismatch,
cash mismatch, missing fill, unknown broker position, the trading block, and the recorded-override
path.

## Documentation requirements
An operational note describing the reconciliation schedule, discrepancy classes, tolerances, and the
override procedure with its audit expectations.

## Completion notes
_Not started._
