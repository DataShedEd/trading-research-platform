# QNT-008 — Security master storage (Parquet/DuckDB)

- **Ticket ID:** QNT-008
- **Status:** DONE
- **Priority:** P1
- **Epic:** EPIC 2 — Security Master

## Problem
The security master domain models exist only in memory. Without a persistence layer that
round-trips them exactly, every process re-derives the master from provider payloads, and any
precision or type loss on the way to disk (Decimals becoming floats, dates becoming timestamps)
corrupts the spine of the system.

## Objective
Persist the security master tables as Parquet under `data/canonical/securities/` with an explicit
declared schema, provide DuckDB-backed read helpers, and guarantee a deterministic, lossless
round-trip from domain model to Parquet and back.

## Scope
`src/trp/canonical/securities/store.py` with writer and reader functions for the four tables —
`entity`, `security`, `security_status`, `listing`, `identifier_map`; an explicit PyArrow schema per
table; DuckDB helpers for querying the Parquet files by path; validation of QNT-007 invariants
before any write; tests.

Layout:

```
data/canonical/securities/entity.parquet
data/canonical/securities/security.parquet
data/canonical/securities/security_status.parquet
data/canonical/securities/listing.parquet
data/canonical/securities/identifier_map.parquet
```

## Out of scope
Price and corporate-action storage (QNT-018, QNT-014), the resolution service (QNT-009), ingestion
from any provider, schema migration tooling.

## Acceptance criteria
- [x] `write_security_master(...)` and `read_security_master(...)` round-trip a fixture set of all
      five tables such that the returned domain models compare equal to the originals, including
      `Decimal` scale and `date` versus `datetime` typing.
- [x] Each table has an explicitly declared PyArrow schema — no inference from dataframes — with
      `Decimal128` for monetary fields, `date32` for market-local dates, and UTC-stamped
      `timestamp` for knowledge timestamps; a test asserts the on-disk schema matches the declared
      one.
- [x] Writes are atomic: output is written to a temporary path and renamed, so an interrupted write
      never leaves a partially written table readable.
- [x] Writing records that violate the QNT-007 overlap invariant fails with a typed error and
      leaves the existing files untouched.
- [x] A DuckDB helper returns a connection with the five tables registered as views over the Parquet
      files, and a documented example query (identifiers valid on a given date) runs against it.
- [x] Re-writing the same input produces byte-identical files, or, where compression metadata
      prevents that, an identical logical read — asserted by a test.

## Technical notes
DuckDB + Parquet is the only analytical store for Milestone 1 (DEC-003); Polars is the dataframe
library. Decimal handling is the main trap: Polars and PyArrow will happily widen or narrow decimal
types across a write/read cycle, so pin precision and scale in the declared schema and assert
equality of the reconstructed `Decimal` objects, not just their float values (DEC-005).

The security master is small — thousands of rows — so a single file per table with no partitioning
is correct here; partitioning matters for prices (QNT-018), not for this data.

Reads reconstruct Pydantic models through the same validators used at construction, so a
hand-edited or provider-corrupted file fails loudly at load rather than propagating bad rows.
Validation before write plus validation on read is deliberate duplication.

Nulls: open-ended validity (`valid_to = None`) must persist as a genuine Parquet null, never as a
sentinel date. Assert this explicitly, since it is the field every point-in-time query depends on.

## Dependencies
QNT-007 — supplies the identifier records and the overlap invariant this store validates;
transitively QNT-006 for the other four tables.

## Risks
Silent type coercion in the Parquet layer is precisely the failure mode this project forbids;
mitigated by explicit schemas and round-trip equality assertions rather than tolerance-based
comparisons.

## Testing requirements
`tests/canonical/test_security_store.py`. Round-trip equality tests per table; schema assertion
tests; an atomicity test simulating an interrupted write; a null-preservation test for open-ended
`valid_to`. Tests write to a `tmp_path` fixture, never to the real `data/` tree.

## Documentation requirements
`docs/DATA_MODEL.md` gains the concrete Parquet layout and the per-table declared schema (column
names, types, nullability) for the security master.

## Completion notes
2026-08-16. `src/trp/canonical/security_store.py` (single module rather than a
`securities/` subpackage): `write_security_master` / `read_security_master` /
`duckdb_security_master` over five tables (`entities`, `securities`, `listings`,
`status_periods`, `identifiers`) under one directory. Explicit Polars schemas (no
inference); Utf8/Date/UTC-Datetime columns — no monetary fields exist in these tables, so
Decimal128 is not yet exercised (that lands with prices, QNT-013/018). Deterministic row
ordering gives byte-identical rewrites (tested). Writes stage to `.tmp` files and rename
only after all five tables are produced; interrupted writes leave published files untouched
(tested via injected failure). Reads reconstruct Pydantic models, re-running all record and
aggregate invariants — a corrupted-overlap file fails loudly (tested). Open-ended
`valid_to` persists as a genuine null (asserted via DuckDB). The QNT-007 invariant holds by
construction on write since the writer accepts only a validated `SecurityMaster`.
Tests: `tests/canonical/test_security_store.py`.
