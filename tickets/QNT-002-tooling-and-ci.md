# QNT-002 — Lint, typecheck, test toolchain and CI

- **Ticket ID:** QNT-002
- **Status:** DONE
- **Priority:** P1
- **Epic:** EPIC 1 — Project Foundation

## Problem
No automated quality gate; quantitative code without strict typing and tests accumulates silent
errors.

## Objective
`make check` (ruff lint+format, mypy strict, pytest) passes locally and runs identically in
GitHub Actions on every push/PR.

## Scope
`.github/workflows/ci.yml` using astral-sh/setup-uv and `uv sync --locked`; smoke test proving
pytest wiring; `timetravel` pytest marker registered.

## Out of scope
Actual time-travel tests (arrive with data features).

## Acceptance criteria
- [x] `make lint`, `make typecheck`, `make test`, `make check` all pass.
- [x] CI workflow runs the same commands as the Makefile.
- [x] `pytest -m timetravel` is a valid (currently empty) selection.

## Technical notes
CI intentionally has no separate configuration — same commands as local, per DEC-002.

## Dependencies
QNT-001.

## Risks
CI unverified on GitHub until first push (owner controls pushing).

## Testing requirements
`tests/test_smoke.py`.

## Documentation requirements
Commands documented in README and CLAUDE.md.

## Completion notes
2026-08-16. All checks green locally (ruff 0.16, mypy 1.x strict, pytest 9). Commit `QNT-002`.
