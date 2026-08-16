# QNT-089 — Stale-data and duplicate-order detection

- **Ticket ID:** QNT-089
- **Status:** BACKLOG
- **Priority:** P3
- **Epic:** EPIC 16 — Live Trading

## Problem
Two failure modes survive every check in QNT-088 because the inputs look perfectly valid. The first is
stale data: a feed that stopped updating an hour ago still returns a plausible price, and every
calculation downstream is confidently wrong. The second is duplication: a process restarts
mid-rebalance, or a submission times out and is retried, and the same intended trade is placed twice —
doubling the position with no error anywhere in the system.

## Objective
Refuse to trade on stale market data, and make order submission idempotent so that the same intended
order cannot be placed twice across retries or restarts.

## Scope
Data freshness checks with per-data-type maximum age, evaluated against the trading calendar and
session state, applied before signal generation and again before submission; idempotency keys derived
from the rebalance intent, persisted before submission and checked on every submission attempt;
restart recovery that re-queries broker state for in-flight orders before submitting anything new.

## Out of scope
Order size and price safeguards (QNT-088); market-data ingestion reliability itself; the audit trail
(QNT-090); automatic retry policies beyond making retries safe.

## Acceptance criteria
- [ ] Each data type has a configured maximum age evaluated against the trading calendar and session
      state, so a weekend or a market holiday does not read as staleness while an hour-old quote
      during the session does.
- [ ] Stale data blocks trading with an explicit reason and cannot be overridden by configuration
      mid-session; the block covers signal generation as well as submission.
- [ ] Every order carries an idempotency key derived deterministically from its intent (rebalance
      identifier, security, target, session), persisted before submission; a repeat submission with
      the same key is refused and reported as a duplicate.
- [ ] After a restart mid-rebalance, the system re-queries broker order state and reconciles against
      persisted keys before any new submission, demonstrated by a test that kills and resumes a
      simulated rebalance with no duplicate order.
- [ ] A submission whose outcome is unknown (timeout, connection loss) is treated as possibly placed:
      the key is retained and resolution requires querying the broker, never blind resubmission.

## Technical notes
The key must be persisted *before* submission, not after, or the crash window between submission and
persistence reintroduces exactly the duplicate this prevents.

Staleness is per data type and per session state. A daily fundamental is not stale at eight hours; a
quote is stale at eight minutes. Encoding that against the trading calendar rather than wall-clock
elapsed time is what keeps the check from being disabled for producing weekend false positives.

## Dependencies
QNT-087 — the environment separation and halt mechanism these checks trigger into.

## Risks
Timeouts are the genuinely hard case, because both resubmitting and not resubmitting can be wrong;
mitigated by treating unknown outcomes as possibly placed and requiring broker state to resolve them,
which fails towards under-trading rather than double-trading.

## Testing requirements
`tests/execution/test_staleness.py` and `tests/execution/test_idempotency.py`: staleness per data type
including holiday and weekend cases, the trading block, duplicate-key refusal, restart-mid-rebalance
recovery, and unknown-outcome handling.

## Documentation requirements
Freshness thresholds per data type and the idempotency key derivation documented in the live-trading
runbook, including the operator procedure for resolving an unknown-outcome order.

## Completion notes
_Not started._
