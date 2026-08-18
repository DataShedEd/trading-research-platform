# QNT-094 — Ad-hoc data exploration surface

- **Ticket ID:** QNT-094
- **Status:** DONE
- **Priority:** P2
- **Epic:** EPIC 1 — Project Foundation

## Problem
The owner needs to interrogate every dataset directly — raw store contents, repaired
canonical data, universe membership, backtest ledgers — without going through platform code
paths, and without falling into the append-only store's two-sources-per-bar trap.

## Objective
A zero-setup SQL console over all canonical and derived Parquet stores, plus a written
querying cookbook.

## Scope
`src/trp/explore.py` (`uv run python -m trp.explore`, interactive or one-shot) registering
DuckDB views: repaired vs original prices/dividends/splits, membership, security master
tables, and per-run backtest daily/events/rebalances. `docs/QUERYING.md` cookbook covering
the source trap, worked SQL, Polars access, and the point-in-time APIs.

## Acceptance criteria
- [x] `prices` view returns only DEC-020-repaired rows; originals available separately.
- [x] Survivorship spot-check works in plain SQL (Aug-2007 membership shows Northern Rock).
- [x] Backtest event ledger queryable per run with the run name as a column.
- [x] Cookbook documents the trap, the layers, and where every dataset lives.

## Completion notes
2026-08-18. Console + cookbook as scoped; verified live (Compass at 1194p from the
repaired view, Aug-2007 membership, full event-kind reconciliation of the momentum run).
Read-only surface — no store mutation possible from it.
