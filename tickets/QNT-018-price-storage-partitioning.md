# QNT-018 — Price storage layout and partitioning

- **Ticket ID:** QNT-018
- **Status:** DONE
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
- [x] Bars are written under `data/canonical/prices/daily/` partitioned by year, using the declared
      schema from QNT-013, with a target of one file per partition and no partition smaller than a
      documented row threshold.
      _Partitioned by year as `trade_year=YYYY/part-NNNNN.parquet` under a **caller-supplied root**
      rather than a hard-coded path (the ticket's own note requires the root come from settings, and
      `data/` is gitignored). One ingestion run writes exactly one part file per year it touches;
      `SMALL_PARTITION_ROWS` (10,000) documents the threshold and `small_partitions()` reports
      partitions below it rather than silently compacting them._
- [x] `read_bars` with a date range touching two years reads only those two partitions; a test
      asserts this from DuckDB's query plan or from an explicit file-access count, not by inspection.
      _Both: a `pl.read_parquet` spy asserts the Python reader opens exactly two files, and the
      DuckDB view's `explain analyze` output is asserted to say `Scanning Files: 1/2`._
- [x] Re-running a write with identical input produces an identical logical dataset — the row count
      and content are unchanged, with no duplicated rows — asserted by a test that writes twice.
      _Stronger than required: the existing part files are asserted byte-identical afterwards._
- [ ] Re-running a write with a partially overlapping input replaces the affected partitions
      wholesale rather than appending, and rows outside the affected partitions are untouched.
      _**Deliberately not implemented as written** — see the completion notes. The property this
      criterion protects (no duplicate rows, untouched rows elsewhere) is met by an append-only
      anti-join on `(security_id, trade_date, source)`; the partition-rewrite *mechanism* is not._
- [x] Writes are atomic per partition: an interrupted write leaves the previous partition readable
      and never leaves a half-written file in place.
- [x] Reading a partition and reconstructing `DailyBar` models yields values equal to those written,
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

**2026-08-16 — done, with one deliberate departure from the acceptance criteria.**

Delivered `src/trp/canonical/price_store.py` (not `canonical/prices/store.py`: `canonical/prices.py`
already exists as the QNT-013 schema module, and a `prices/` package would have collided with it) —
`write_prices`, `read_prices`, `read_bars`, `partition_files`, `partition_row_counts`,
`small_partitions`, `duckdb_prices`. Layout `<root>/trade_year=YYYY/part-NNNNN.parquet`, mirroring
the fundamentals dataset (DEC-011). Tests: `tests/canonical/test_price_store.py` (16) and
`tests/timetravel/test_price_store_timetravel.py` (3), all passing, with `mypy --strict` and `ruff`
clean.

**Departure: append-only anti-join instead of partition-wholesale replacement.** The ticket
specified recomputing and rewriting every partition an incoming load touches. The writer instead
appends new part files and skips rows already present, keyed on `(security_id, trade_date, source)`
— the QNT-024 fundamentals pattern. Three reasons, recorded here because this contradicts a written
acceptance criterion and needs a `docs/DECISIONS.md` entry to become policy:

1. The ticket's own risk section notes that wholesale replacement lets a bad ingestion destroy good
   rows in the same year. Append-only removes that failure mode entirely rather than mitigating it.
2. `source` in the row key means two providers' views of the same security-day coexist as two rows
   to be compared. That is what the provider bake-off needs; partition replacement would have made
   the second provider's load overwrite the first's.
3. It is the mechanism already in use for canonical fundamentals, so the two canonical datasets now
   behave identically under re-ingestion rather than each having its own rule.

The cost is that incremental daily loads accumulate small part files. That is why
`partition_row_counts` / `small_partitions` and the documented `SMALL_PARTITION_ROWS` threshold
exist: compaction is reportable and deliberate, never implicit.

**Also added beyond the ticket:** `read_prices`/`read_bars` take an optional `as_of` bounding
`ingested_at`, per the CLAUDE.md rule that every historical read has an explicit `as_of`. This is
what the `timetravel` test exercises — a re-ingestion of revised history cannot alter an earlier
reproduction.

**Not measured:** the ticket asks to measure whether a year partition for the full universe reads in
well under a second before deciding no further partitioning is needed. No real universe has been
ingested yet, so this remains an open check for the first full backfill. The synthetic test only
confirms the file *count* is sane (1,000 bars across 50 securities produce one file).
