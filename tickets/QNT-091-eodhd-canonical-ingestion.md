# QNT-091 — EODHD canonical ingestion pipeline

- **Ticket ID:** QNT-091
- **Status:** IN_PROGRESS
- **Priority:** P1
- **Epic:** EPIC 3 — Market Data

## Problem
The platform can fetch and archive EODHD payloads (QNT-026/031) and can store canonical bars
and corporate actions (QNT-013/014/018), but nothing connects them: there is no transform
from EODHD's raw JSON to `DailyBar`, `Split` and `Dividend` records. Without it the curated
FTSE 100 membership (QNT-039) references securities with no data behind them.

## Objective
Deterministic, re-runnable transforms from raw EODHD payloads to canonical records, plus a
resumable backfill runner that fetches (raw-first) and canonicalises prices and corporate
actions for a given set of securities.

## Scope
`src/trp/canonical/ingest_eodhd.py`: `bars_from_eodhd`, `splits_from_eodhd`,
`dividends_from_eodhd` (payload bytes + security context → validated domain records, with
per-row rejects reported, never silently dropped) and a backfill runner writing through the
QNT-026 raw store into the QNT-018 price store and a corporate-actions Parquet store.
Unit tests on recorded payload shapes; a live backfill for the FTSE 100 constituent set.

## Out of scope
Fundamentals canonicalisation from EODHD (needs the QNT-021 mapping tables extended with
EODHD's field names — its own piece of work); Tiingo/FMP transforms; daily incremental
refresh via `eod-bulk-last-day` (future ticket once backfill exists).

## Acceptance criteria
- [ ] EODHD LSE price rows become `DailyBar`s with `currency="GBX"` (pence, as quoted) and
      Decimal values taken from the JSON text without float round-tripping; the provider's
      `adjusted_close` lands in `provider_adjusted_close` only.
- [ ] EODHD dividend rows preserve their stated `currency` verbatim (EODHD reports LSE
      dividends in GBP while quoting prices in GBX — the unit trap must remain visible);
      split rows parse `"N/M"` ratio strings exactly.
- [ ] Rows that fail domain validation are collected and reported per security with the
      offending values; a batch never silently shrinks.
- [ ] The backfill runner is resumable (skips securities whose raw payloads already exist),
      raw-first (archive before transform), and paced under the provider's rate limits.
- [ ] `make check` green; live FTSE-constituent backfill completes with a coverage report
      (bars per security, date spans, actions counts, rejects).

## Technical notes
Numeric fidelity: parse JSON with `parse_float=Decimal` so `14.27` never becomes
`14.269999…`. `available_at` for corporate actions follows DEC-007 (imputed at ex-date,
flagged) since EODHD provides no announcement timestamps for them.

## Dependencies
QNT-013/014/018 (canonical stores), QNT-026/031 (raw store, adapter), QNT-039 (the
constituent set that defines the backfill).

## Risks
EODHD payload quirks (nulls, zero-volume placeholder rows during suspensions — see the
Carillion finding) must surface as reported rejects, not crashes and not silent fixes.

## Testing requirements
`tests/canonical/test_ingest_eodhd.py` on recorded shapes incl. a malformed row; reject
reporting; Decimal fidelity assertions.

## Documentation requirements
DATA_MODEL/ARCHITECTURE note that EODHD is the first wired canonical source; coverage
report location documented in the ticket's completion notes.

## Completion notes
_Not started._
