# QNT-090 — Audit trail

- **Ticket ID:** QNT-090
- **Status:** BACKLOG
- **Priority:** P3
- **Epic:** EPIC 16 — Live Trading

## Problem
After a bad trading day the only question worth answering is what the system actually did and why,
and ordinary application logs cannot answer it: they are rotated, they are edited, they omit the
inputs, and they interleave the decision with the debug output. Reconstructing a decision months later
requires a record designed for that purpose — one where a missing or altered entry is detectable
rather than merely unlikely.

## Objective
Maintain an append-only, tamper-evident audit trail of every trading decision, order, fill, safeguard
rejection, override and kill-switch event, sufficient to reconstruct any session.

## Scope
An append-only audit log with structured entries: signal generation with input data versions,
portfolio construction decisions, every order and its intent, safeguard checks passed and failed,
overrides with actor and reason, fills, reconciliation outcomes, kill-switch and live-enablement
events. Hash chaining for tamper evidence, a verification command, and a query interface for
reconstructing a session.

## Out of scope
Order and fill capture for cost calibration (QNT-086), which this references rather than duplicates;
external log shipping; cryptographic signing or third-party timestamping; regulatory reporting.

## Acceptance criteria
- [ ] Every decision, order, fill, safeguard rejection, override and kill-switch event is written to
      the trail before or at the moment it takes effect, and no execution path can act without an
      entry — asserted by a test that exercises a full rebalance and checks trail completeness.
- [ ] Entries are append-only and hash-chained, each including the previous entry's hash; a
      verification command detects modification, deletion or reordering of any entry.
- [ ] Every decision entry records the input data versions and the git commit, so a decision can be
      reproduced with the same rigour as a research run (QNT-064).
- [ ] A session can be reconstructed from the trail alone into a readable chronological narrative of
      what was decided, attempted, rejected and filled.
- [ ] A write failure to the trail halts trading rather than proceeding unlogged.

## Technical notes
Hash chaining gives tamper *evidence*, not tamper *prevention* — an actor with filesystem access can
rewrite the chain wholesale. That is the correct level of protection for a personal platform: it
detects accidental corruption and casual editing, which are the realistic threats, without pretending
to defend against the operator, who is also the owner.

The trail is a separate concern from the QNT-086 order store even though they overlap: capture exists
to calibrate costs, the trail exists to answer "why". Cross-reference by identifier rather than
duplicating the fill detail.

## Dependencies
QNT-087 — the environment separation and kill-switch events the trail must record.

## Risks
Halting trading on a log write failure trades availability for auditability, deliberately; the risk of
an unlogged live session is worse than the risk of a missed rebalance. The other risk is a trail so
verbose it is unreadable, mitigated by the session-reconstruction requirement, which forces the entry
set to be structured for narrative rather than volume.

## Testing requirements
`tests/execution/test_audit_trail.py`: completeness over a full simulated rebalance, hash-chain
verification detecting modification, deletion and reordering, session reconstruction output, and the
write-failure halt.

## Documentation requirements
Entry schema, the tamper-evidence guarantee and its explicit limits, and the verification and
reconstruction procedures documented in the live-trading runbook; `docs/ARCHITECTURE.md`
execution-boundary section references the trail as mandatory for live operation.

## Completion notes
_Not started._
