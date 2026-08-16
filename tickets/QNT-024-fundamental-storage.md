# QNT-024 — Fundamental storage layout

- **Ticket ID:** QNT-024
- **Status:** BACKLOG
- **Priority:** P1
- **Epic:** EPIC 4 — Fundamental Data

## Problem
The fundamentals dataset is long and narrow — one row per security, statement, line item, period
and revision — and it is queried in an awkward pattern: a handful of line items across thousands of
securities, filtered by an availability timestamp. Chosen badly, the physical layout either
produces tens of thousands of tiny Parquet files or forces a full scan for every as-of query. Two
correctness hazards ride along with the performance one: Parquet round-trips can quietly turn
`Decimal` into `float` and drop timezone information, and a re-run of ingestion can duplicate rows
or, worse, overwrite the revision history that QNT-022 exists to preserve.

## Objective
Define and implement the Parquet layout for canonical fundamentals under
`data/canonical/fundamentals/`, with a writer and reader that preserve `Decimal` and UTC exactly,
partition sensibly for as-of queries, and make re-ingestion idempotent without rewriting history.

## Scope
`src/trp/canonical/fundamentals/storage.py`: the Arrow/Parquet schema derived from
`FundamentalValue`, `write_fundamentals` and `read_fundamentals` functions, the partitioning
scheme, a dataset-manifest or ingestion-log record capturing what was written and when, and
idempotence logic. Tests including a round-trip test and an idempotent re-ingestion test.

## Out of scope
The domain record (QNT-020); revision classification rules (QNT-022) — this ticket persists the
outcome of those rules but does not decide them; the public as-of query API and its DuckDB views
(QNT-025); the raw payload layer under `data/raw/` (QNT-026).

## Acceptance criteria
- [ ] A documented partitioning scheme is implemented under `data/canonical/fundamentals/`,
      chosen for the dominant query pattern (line items across many securities filtered by
      `available_at`) and justified in the technical notes with the resulting file-count and
      file-size characteristics at the expected data volume.
- [ ] `Decimal` values survive a write/read round trip exactly, including trailing-zero scale where
      it is significant, and a test asserts the returned type is `Decimal` — not `float` and not a
      string.
- [ ] All three timestamps (`filed_at`, `available_at`, `revised_at`) round-trip as timezone-aware
      UTC with microsecond-or-better precision, and `period_end` round-trips as a `date` rather
      than a midnight-local datetime.
- [ ] Re-running ingestion over an identical payload is a no-op: row count and file contents are
      unchanged, and no partition is rewritten. Re-running over a payload containing one new
      revision appends exactly one row and leaves every pre-existing row byte-identical.
- [ ] Writes are atomic at the partition level — an interrupted write leaves the dataset readable
      and in its previous state rather than half-written — and the ingestion log records dataset
      version, source, row counts and write timestamp for reproducibility.
- [ ] `read_fundamentals` can load a subset by security, line item and period range without
      reading the whole dataset, demonstrated by a test asserting the files touched.

## Technical notes
DEC-003 makes Parquet plus DuckDB the only analytical store, and `docs/ARCHITECTURE.md` asks for
intelligent partitioning that avoids excessive tiny files. Partitioning by period year is the
obvious starting point; partitioning additionally by statement is worth measuring, while
partitioning by security is almost certainly wrong at this row width. Whatever is chosen, record
the measurement that justified it — this is a decision later tickets will inherit.

`Decimal` in Parquet needs an explicit `decimal128` Arrow type with a fixed precision and scale
chosen to cover the magnitudes involved: fundamental values span from per-share pence to hundreds
of billions in reporting currency, so the naive scale used for prices will overflow. Choose the
precision/scale deliberately, assert it in the schema, and make an out-of-range value an error
rather than a silent truncation. Do not use `float64` anywhere in this dataset (DEC-005).

Idempotence combines with QNT-022's append-only rule: the writer must never rewrite an existing
row, so "upsert" is not available. The workable pattern is to compute a stable row key (revision
key plus `revision_sequence`) and skip rows already present, writing only genuinely new rows into
new files within the partition. Retaining an ingestion log makes it possible to answer "when did
this row arrive and from which raw payload?", which QUANT_PRINCIPLES §4 requires for reproducible
results.

Atomicity on a local filesystem is achievable by writing to a temporary path and renaming; keep it
simple, and note in the docstring that DEC-003 accepts a single-writer model, so no concurrent-
writer locking is required.

Values are stored in reporting currency (QNT-023); the storage layer performs no conversion,
no normalisation, and no imputation — it persists exactly what it is given.

## Dependencies
QNT-020 — the record definition the Parquet schema is derived from, including the fields whose
round-trip fidelity is under test.

## Risks
A partitioning choice that looks fine on fixture data can become unworkable at full universe scale,
and changing it later means rewriting the dataset. Mitigated by measuring at realistic row counts
with synthetic data before committing, and by the fact that canonical data is always re-derivable
from immutable raw payloads. A quieter risk is `Decimal` precision loss appearing only for large
balance-sheet values; mitigated by explicitly testing magnitudes at both extremes.

## Testing requirements
`tests/canonical/test_fundamental_storage.py` covering the round trip (including a very large
balance-sheet magnitude and a small per-share value), timestamp fidelity, partition pruning,
atomicity under a simulated interrupted write, and idempotent re-ingestion. Plus
`tests/timetravel/test_fundamental_storage_asof.py` (pytest marker `timetravel`) asserting that a
read filtered by `available_at` never returns a row written from a later-dated payload — the
storage-level guarantee that QNT-025's query API depends on. Include a synthetic-volume test
generating a realistic number of rows to validate the file-count characteristics claimed above.

## Documentation requirements
`docs/ARCHITECTURE.md` storage section gains the fundamentals partitioning scheme alongside the
existing prices example. A `DECISIONS.md` entry recording the partitioning choice and the chosen
`decimal128` precision/scale, since both are expensive to change once data exists.

## Completion notes
_Not started._
