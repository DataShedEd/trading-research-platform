# QNT-087 — Live/paper environment separation and kill switch

- **Ticket ID:** QNT-087
- **Status:** BACKLOG
- **Priority:** P3
- **Epic:** EPIC 16 — Live Trading

## Problem
The two failures that matter most in live trading are trading real money while believing you are on
paper, and being unable to stop. Both are configuration problems, not algorithm problems: a shared
credentials file with an environment flag, or a system whose only way to halt is to kill a process and
hope no order is in flight. Separation and a halt mechanism have to exist before any live order is
possible, and they have to be verifiable rather than merely intended.

## Objective
Physically separate live and paper configurations and credentials, and provide a global kill switch
that halts all order flow, with live trading enabled only by an explicit, logged action.

## Scope
Separate configuration and credential files per environment with no shared file containing both; an
environment identity that every execution component asserts at startup and before every order; a kill
switch with durable state that survives restart and halts all order submission; an explicit
enable-live action requiring deliberate confirmation and producing a log record; startup refusal when
environment identity is ambiguous.

## Out of scope
Order-level safeguards (QNT-088); stale-data and duplicate detection (QNT-089); the audit trail
(QNT-090); automated trading schedules; secret management infrastructure beyond file separation and
permissions.

## Acceptance criteria
- [ ] Live and paper credentials live in separate files that are never both loaded in one process; a
      configuration containing both, or an environment that cannot be determined unambiguously,
      refuses to start.
- [ ] The environment identity is asserted immediately before every order submission, and a mismatch
      between the configured environment and the connected account raises and halts rather than
      proceeding.
- [ ] The kill switch halts all order submission within a documented time, persists its state across
      process restart, and can be engaged without the application running.
- [ ] Enabling live trading requires an explicit action distinct from ordinary configuration, is
      recorded with actor, timestamp and reason, and defaults to disabled after any restart or
      deployment.
- [ ] The account identifier connected to is compared with the expected identifier for the
      environment, and a mismatch is fatal.

## Technical notes
Kill-switch state living in a file that can be created without the application running is deliberate:
the mechanism must work when the application is unresponsive, which is when it is most needed.
Default-closed after restart applies to live enablement too — an unattended restart must never come
back trading.

Checking the connected account identifier, not just the configured environment name, is what catches
the genuinely dangerous case of correct-looking configuration pointed at the wrong account.

## Dependencies
QNT-085 — reconciliation and its trading block, which live trading depends on being proven in paper.

## Risks
Safeguards that make routine operation tedious get bypassed; mitigated by keeping friction
concentrated at the enable-live boundary rather than in day-to-day paper use. The residual risk is
that this ticket's guarantees are assumed rather than tested — hence the explicit test requirements.

## Testing requirements
`tests/execution/test_environment_separation.py`: ambiguous-configuration refusal, account-identifier
mismatch halt, kill-switch engagement blocking submission, kill-switch persistence across restart, and
live-disabled-by-default after restart.

## Documentation requirements
An operational runbook covering how to engage the kill switch (including without the application
running), how live trading is enabled, and what is checked at startup; `docs/ARCHITECTURE.md`
execution-boundary section updated to reference it.

## Completion notes
_Not started._
