# QNT-114 — FTSE 250 data-quality gates and golden momentum observations

- **Ticket ID:** QNT-114
- **Status:** DONE
- **Priority:** P1
- **Epic:** EPIC 8 — Backtesting Engine
- **Depends on:** QNT-111, QNT-112, QNT-113

## Problem
The strategy must not run on the new universe until it passes the same class of gates
the FTSE 100 earned: PIT membership, delisted preservation, identity/ticker
transitions, GBX/GBP repair, splits/dividends, lifecycle actions, stale prices,
missing observations, future-data invariance.

## Objective
FTSE 250 equivalents of the FTSE 100 gates, plus golden 12-1 momentum observations at
several historical dates through the SHARED input assembly (computable_inputs — no
FTSE-250-specific factor path), independently reproduced as in the FTSE 100 golden gate.

## Scope
- Gate suite: membership PIT + survivorship, coverage-with-exceptions, overlap (from
  QNT-111), unit-repair extension to new names, lifecycle delistings for FTSE 250
  leavers, benchmark gate (QNT-113).
- Golden cross-sections including: a continuing FTSE 250 member, a later promotion to
  FTSE 100, a recent demotion from FTSE 100, a delisting, and a corporate-action case;
  independent textbook reconstruction to 1e-9.

## Acceptance criteria
- [x] All gates green (or explicit documented exceptions per project rules) BEFORE any
      strategy run on the universe.
- [x] Golden fixture pinned; regeneration deliberate-only.

## Completion notes
- 46 gates green before the holdout ran: membership PIT/overlap/identity/survivorship
  (QNT-111 suite), FTSE 100 goldens + reproduction, FTSE 250 goldens
  (tests/gate/test_ftse250_golden_gate.py — same convention, same independent
  reconstruction, SHARED computable_inputs assembly), benchmark gates.
- Golden dates 2016/2019/2020-03/2025; tops are real market stories (JD Sports +83%
  2016, Future +146% 2019, Petropavlovsk +122% COVID, Metro Bank +214% 2025); boundary
  cases asserted (Royal Mail demotion era, Carillion pre-failure, Aberdeen chain).
- The goldens caught a live defect before the run: UK Commercial Property Trust showed
  +15,402x momentum from an 11-quarter 100x dividend mis-scale (0.92 GBP printed for
  0.92p) that the sub-£2 Segro exemption shielded — fixed generically with the
  out-of-family amount rule (>=20x the security's own median relabels), 49 records
  corrected, FTSE 100 runs verified unaffected (reproduction gate).
