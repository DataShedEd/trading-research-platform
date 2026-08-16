# QNT-018 — Price storage layout and partitioning

- **Ticket ID:** QNT-018
- **Status:** BACKLOG
- **Priority:** P1
- **Epic:** EPIC 3 — Market Data

## Problem
Daily bars for a few thousand securities over twenty years is tens of millions of rows. Written
naively — one file per security, or one file per security-day — it becomes hundreds of thousands of
tiny Parquet files that make every query slow and every re-ingestion a duplication risk. Written as
one enormous file, every read scans everything.

## Objective
A partitioned Parquet layout under `data/canonical/prices/` with writer and reader helpers,
verified DuckDB partition pruning, and idempotent re-writes so that re-running ingestion cannot
duplicate rows.

## Scope
`src/trp/canonical/prices/store.py` providing `write_bars(bars)`, `read_bars(security_ids, start,
end)`, and a DuckDB view registration helper; the partition scheme; idempotency via deterministic
partition-file replacement; tests including a pruning assertion.

Layout, partitioned by year:

```
data/canonical/prices/daily/year=2015/part-0.parquet
data/canonical/prices/daily/year=2016/part-0.parquet
```

## Out of scope
Adjustment factors storage (QNT-015 writes to `data/derived/`), intraday data, provider ingestion
scheduling, compaction of historical partitions beyond what the writer does naturally.

## Acceptance criteria
- [ ] Bars are written under `data/canonical/prices/daily/` partitioned by year, using the declared
      schema from QNT-013, with a target of one file per partition and no partition smaller than a
      documented row threshold.
- [ ] `read_bars` with a date range touching two years reads only those two partitions; a test
      asserts this from DuckDB's query plan or from an explicit file-access count, not by inspection.
- [ ] Re-running a write with identical input produces an identical logical dataset — the row count
      and content are unchanged, with no duplicated rows — asserted by a test that writes twice.
- [ ] Re-running a write with a partially overlapping input replaces the affected partitions
      wholesale rather than appending, and rows outside the affected partitions are untouched.
- [ ] Writes are atomic per partition: an interrupted write leaves the previous partition readable
      and never leaves a half-written file in place.
- [ ] Reading a partition and reconstructing `DailyBar` models yields values equal to those written,
      including `Decimal` scale and `date` typing.

## Technical notes
Year partitioning is the recommendation in `docs/ARCHITECTURE.md` and is right for daily data: a
typical research query spans a date range across all securities, so pruning by date is what pays,
while pruning by security would produce the tiny-file problem. Sort rows within each partition by
`security_id` then `trade_date` so that row-group statistics allow DuckDB to skip within a file as
well as between partitions.

Idempotency is achieved by making the partition the unit of replacement: recompute the full content
of every partition the incoming data touches and rewrite it atomically, rather than appending and
deduplicating afterwards. Append-plus-deduplicate is where duplicate rows survive, and a duplicated
bar silently doubles a day's weight in any aggregate.

Note the distinction from the raw layer: `data/raw/` is immutable and append-only (it is the audit
trail), whereas `data/canonical/` is a deterministic, re-runnable transform of it. Rewriting a
canonical partition is therefore correct and expected, provided it is reproducible from raw.

`data/` is gitignored, so tests must write to `tmp_path` and the helpers must take a root path from
settings (QNT-003) rather than assuming a fixed location.

Measure before adding complexity: if a year partition for the full universe is comfortably read in
well under a second, no further partitioning is warranted for Milestone 1.

## Dependencies
QNT-013 — supplies the `DailyBar` model and the declared Parquet schema this layout persists.

## Risks
Partition-wholesale replacement means a bad ingestion can destroy good rows in the same partition.
Mitigated by the canonical layer being rebuildable from immutable raw payloads, and by writing
atomically so a failure mid-write leaves the previous partition intact.

## Testing requirements
`tests/canonical/test_price_store.py` plus `tests/timetravel/test_price_store_timetravel.py`
(pytest marker `timetravel`). Required: double-write idempotency; overlapping-write partition
replacement; partition pruning verified programmatically; round-trip type fidelity; atomicity under
a simulated interruption. The `timetravel` test asserts that a read bounded by an `as_of` ingestion
timestamp cannot return bars ingested later, so that a re-ingestion of revised history does not
alter an earlier reproduction.

## Documentation requirements
`docs/DATA_MODEL.md` gains the concrete price storage layout and partition scheme.
`docs/ARCHITECTURE.md` storage section updated if the measured partitioning choice differs from the
"e.g. prices by year" guidance already recorded there.

## Completion notes
_Not started._
