# QNT-100 — Lifecycle delisting records from curated + price evidence

- **Ticket ID:** QNT-100
- **Status:** DONE
- **Priority:** P2
- **Epic:** EPIC 3 — Market Data Core

## Problem
No delisting/merger corporate actions are canonicalised (EODHD's delisted list served
identity validation only; its fundamentals `IsDelisted` field is unpopulated even for
dead names), so departures resolve through DEC-019 forced exits: correct proceeds, but
15 days late and always warned. The evidence to do better already exists: the curated
FTSE history's removal reasons (41 acquisitions, 14 mergers, 6 adjudicable delistings)
and the repaired price series' own endings.

## Objective
Derive a canonical delisting-action dataset for every FTSE-100-ever security whose price
series has ended, with reasons from curated evidence where it exists and an honest
UNKNOWN otherwise; resolve non-failure delistings at the last traded close ON the
delisting date rather than 15 days later.

## Scope
- `DelistingReason.UNKNOWN` added to the domain enum (claiming ACQUISITION without
  evidence would be fabrication; UNKNOWN still resolves at last close, which
  approximates acquisition consideration and collapsed-failure value alike).
- `trp.canonical.lifecycle`: series-end detection against the repaired source; reason
  resolution from curated removal entries (ticker matched within a window of the last
  trade, ambiguity -> UNKNOWN) plus a small adjudication table (NMC Health and Thomas
  Cook as FAILURE; Invesco/Just Eat/Ferguson/CRH/Flutter as EXCHANGE_MOVE);
  `lifecycle_delistings.parquet` with a build report.
- Engine: a DelistingAction without cash terms resolves at the last close for every
  reason except FAILURE (which stays a write-off); DEC-023 records the convention.
- Runner loads the lifecycle records; DEC-019 forced exits become the residual backstop.

## Acceptance criteria
- [x] Every master security whose repaired series ended >15 days before the dataset edge
      has a record, with reason provenance in the report.
- [x] Engine resolves non-failure records at last close on the ex-date (tested); FAILURE
      still writes off; DEC-019 backstop still covers securities without records.
- [x] Momentum tearsheet re-run shows forced-exit warnings materially reduced.

## Completion notes
2026-08-21. 57 lifecycle records: 17 ACQUISITION (curated removal evidence, windowed
ticker match so recycled tickers cannot attach the wrong exit), 2 FAILURE (adjudicated —
the derived ex-dates land exactly on Thomas Cook's 2019-09-23 liquidation and NMC's
2020-04-28 cancellation), 4 EXCHANGE_MOVE, 34 UNKNOWN with the DEC-023 rationale in
their provenance. Engine: non-failure records resolve at the last close ON the ex-date
(tested); FAILURE still writes off; DEC-019 stays as backstop and now fires ZERO times
(was 10). Alongside: the Melrose segment re-adjudication (vendor basis flips to
GBX-native at the April 2023 demerger) regenerated the repaired dataset as eodhd-gbx2 —
append-only, v1 retained — with all consumers on constants; full factor store
re-materialised (4,000 files) and trp.duckdb rebuilt. Registered run
momentum-baseline-r3 on the corrected store: CAGR 10.69% (from 10.90%), Sharpe 0.552,
max DD unchanged — ~20bp of the old result was Melrose mark inflation plus late exits,
removed in the conservative direction. The reproduction gate now targets the
newest-by-mtime record (older records legitimately stop reproducing across data
re-adjudications; their manifests pin the prior versions and rerun() reports the diff).
845 default + 22 gate green.
