# QNT-001 — Repository scaffold and package skeleton

- **Ticket ID:** QNT-001
- **Status:** DONE
- **Priority:** P1
- **Epic:** EPIC 1 — Project Foundation

## Problem
Empty repository; no structure, dependency management, or conventions exist.

## Objective
A working uv-managed Python project with src layout, pinned Python, core dependencies, and the
directory skeleton for the Milestone 1 packages.

## Scope
`pyproject.toml` (metadata, deps, ruff/mypy/pytest configuration), `.python-version`,
`.gitignore`, `README.md`, `CLAUDE.md` (working conventions), `Makefile`, package skeleton
(`src/trp/` with `domain`, `providers/adapters`, `ingestion`, `canonical`, `bakeoff`), `py.typed`.

## Out of scope
CI (QNT-002), config/logging code (QNT-003), docs suite (QNT-004), tickets (QNT-005).

## Acceptance criteria
- [x] `uv sync` creates a working environment on Python 3.12.
- [x] Package `trp` imports; `py.typed` present.
- [x] ruff, mypy strict, pytest configured in `pyproject.toml` (DTZ rules enabled).
- [x] `data/` gitignored; README states principles and layout.

## Technical notes
Package named `trp` to avoid stdlib collisions (DEC-001). Tool configuration lives in
`pyproject.toml` to keep a single source of tool truth.

## Dependencies
None.

## Risks
None material.

## Testing requirements
Covered by QNT-002 (smoke test + full toolchain run).

## Documentation requirements
README and CLAUDE.md written here; full docs suite is QNT-004.

## Completion notes
2026-08-16. uv 0.16.x via Homebrew; deps: polars, duckdb, pyarrow, pydantic, pydantic-settings,
httpx; dev: pytest, ruff, mypy. `uv.lock` committed. Commit `QNT-001`.
