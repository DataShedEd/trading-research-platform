# QNT-100 — Lifecycle delisting records from curated + price evidence

- **Ticket ID:** QNT-100
- **Status:** IN_PROGRESS
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
- [ ] Every master security whose repaired series ended >15 days before the dataset edge
      has a record, with reason provenance in the report.
- [ ] Engine resolves non-failure records at last close on the ex-date (tested); FAILURE
      still writes off; DEC-019 backstop still covers securities without records.
- [ ] Momentum tearsheet re-run shows forced-exit warnings materially reduced.

## Completion notes
_In progress._
