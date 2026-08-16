# QNT-003 — Configuration and logging

- **Ticket ID:** QNT-003
- **Status:** DONE
- **Priority:** P1
- **Epic:** EPIC 1 — Project Foundation

## Problem
Components need consistent access to data-layer paths, provider credentials, and logging without
ad-hoc environment reads or secrets leaking into logs.

## Objective
Typed settings (env prefix `TRP_`, optional `.env`) exposing data-layer paths and provider API
keys as secrets; stdlib logging setup with UTC timestamps.

## Scope
`trp/config.py` (`Settings`, `load_settings`, `ensure_data_dirs`), `trp/logging.py`
(`setup_logging`), tests.

## Out of scope
Per-component configuration (added by those components); log shipping/rotation.

## Acceptance criteria
- [x] Defaults: `data/raw`, `data/canonical`, `data/derived`.
- [x] Env overrides work; API keys are `SecretStr` and absent from `repr`.
- [x] `setup_logging` idempotent, UTC timestamps with explicit `Z`.

## Technical notes
Settings constructed at entry points via `load_settings()`, never at import time. Plain stdlib
logging by design — no framework (ARCHITECTURE: simple, inspectable).

## Dependencies
QNT-001, QNT-002.

## Risks
None material.

## Testing requirements
`tests/test_config.py`, `tests/test_logging.py`.

## Documentation requirements
Documented in CLAUDE.md commands/conventions.

## Completion notes
2026-08-16. 5 tests passing; secrets verified absent from repr. Commit `QNT-003`.
