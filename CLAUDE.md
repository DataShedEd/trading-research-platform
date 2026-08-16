# Working conventions for this repository

This is a personal quantitative research platform. The owner is technically and mathematically
capable; do not simplify unnecessarily. Correctness beats convenience everywhere.

## Read first

- `docs/QUANT_PRINCIPLES.md` — non-negotiable: point-in-time correctness, survivorship-bias
  avoidance, corporate-action handling, reproducibility.
- `docs/ARCHITECTURE.md` and `docs/DATA_MODEL.md` — how the system fits together.
- `docs/DECISIONS.md` — never silently change a decision recorded there; append a new entry.
- `tickets/INDEX.md` — the backlog and its statuses.

## Workflow

Work ticket by ticket from `tickets/`. Before starting a ticket: read its dependencies, confirm
they are DONE, set status to IN_PROGRESS. On completion: tests pass, docs updated, decisions
logged, completion notes written, status set to DONE, and one commit per ticket with the ticket ID
first in the message (e.g. `QNT-006: security master domain model`). If blocked, mark BLOCKED with
a precise reason. Statuses: BACKLOG, READY, IN_PROGRESS, BLOCKED, DONE.

## Commands

```sh
uv sync                  # install/refresh environment
make test                # pytest
make lint                # ruff check + format --check
make typecheck           # mypy --strict
make check               # lint + typecheck + test
uv run pytest -m timetravel   # leakage tests only
```

## Code conventions

- Typed Python (mypy strict). Pydantic v2 frozen models for domain objects.
- All timestamps timezone-aware UTC (`DTZ` ruff rules enforce this). Dates for market-local
  concepts (trading days, period ends) are `datetime.date`.
- `Decimal` for prices, dividends, and per-share values in canonical stores; floats only in
  derived analytics.
- Polars for dataframe work; DuckDB/Parquet for storage; SQL where set-based logic is clearer.
- Deterministic functions; no hidden state; no silent data coercion; raw provider payloads are
  never discarded or mutated.
- Every data-access API that reads historical data takes an explicit `as_of` argument.

## Testing

Quantitative correctness over coverage numbers. Any feature touching historical data needs a
time-travel test (marker `timetravel`) proving future information cannot leak. Corporate-action
handling needs worked numeric examples as fixtures.

`tests/lifecycle/` is the Epic 2 (security master) regression harness: data-driven company
lifecycles (failure, rename + ticker reuse, acquisition) asserted directly, after a storage
round-trip, and through the point-in-time facade. Anything touching the security master must
leave it green; run it first when a downstream result looks wrong.
