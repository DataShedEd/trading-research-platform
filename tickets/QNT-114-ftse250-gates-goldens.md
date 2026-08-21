# QNT-114 — FTSE 250 data-quality gates and golden momentum observations

- **Ticket ID:** QNT-114
- **Status:** BACKLOG
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
- [ ] All gates green (or explicit documented exceptions per project rules) BEFORE any
      strategy run on the universe.
- [ ] Golden fixture pinned; regeneration deliberate-only.

## Completion notes
_Not started._
