# QNT-113 — FTSE 250 total-return benchmark

- **Ticket ID:** QNT-113
- **Status:** BACKLOG
- **Priority:** P1
- **Epic:** EPIC 8 — Backtesting Engine
- **Depends on:** QNT-055 (DONE), DEC-021 pattern

## Problem
The holdout's pre-registered primary metric is IR vs an FTSE 250 total-return
benchmark. It must be investable, dividend-inclusive, unit-consistent, and validated —
not fabricated pre-inception.

## Objective
Research, ingest and validate an FTSE 250 TR benchmark (ETF route per DEC-021 unless a
better series exists): distributing class + dividends reinvested at ex-date close,
cross-validated against an accumulating class where one exists.

## Scope
- Candidate research (iShares MIDD, Vanguard VMID, HSBC HMCX, ...): inception, TER,
  FULL FTSE 250 vs ex-investment-trusts variant — the index variant must be stated.
- Ingestion via the QNT-096/benchmark machinery; same quality checks as ISF.
- Disclosure: excess returns are vs an investable ETF (fees inside), not the paper
  index; experiment start bounded by reliable benchmark coverage.

## Acceptance criteria
- [ ] Benchmark ingested, unit-checked, validated (accumulating-class or index-return
      cross-check where available); gate added.
- [ ] DEC entry recording the choice, its variant (full/ex-IT), fees and caveats.

## Completion notes
_Not started._
