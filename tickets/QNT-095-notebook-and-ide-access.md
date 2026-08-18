# QNT-095 — Notebook and IDE (JDBC) data access

- **Ticket ID:** QNT-095
- **Status:** DONE
- **Priority:** P2
- **Epic:** EPIC 1 — Project Foundation

## Problem
QNT-094's console covers ad-hoc terminal queries, but the owner works in notebooks and
IDE database tools (DataGrip); both need first-class, documented access that inherits the
same repaired-source defaults.

## Objective
JupyterLab with a worked starter notebook, and a rebuildable DuckDB database file any
JDBC client can open, both defaulting to the DEC-020-repaired datasets.

## Scope
Dev dependencies jupyterlab + matplotlib; `notebooks/explore.ipynb` (executed, outputs
committed); `trp.explore --build-db` writing `data/trp.duckdb` (view definitions only,
absolute paths, no data copied); `make lab` / `make db`; QUERYING.md sections.

## Acceptance criteria
- [x] The starter notebook executes end-to-end headlessly (nbconvert --execute).
- [x] `data/trp.duckdb` opens read-only from an arbitrary working directory and serves
      all views (verified: 1,256,090 bars via the `prices` view from /tmp).
- [x] Documentation covers the read-only-connection locking caveat and driver-version
      note for DataGrip/DBeaver.

## Completion notes
2026-08-18. As scoped. The database file holds only views over the Parquet stores, so a
`make db` rebuild after any ingestion refreshes it instantly and nothing is duplicated;
IDE sessions are read-only by instruction so they never hold the writer lock.
