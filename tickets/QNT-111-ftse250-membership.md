# QNT-111 — FTSE 250 historical membership + overlap gate

- **Ticket ID:** QNT-111
- **Status:** IN_PROGRESS
- **Priority:** P1
- **Epic:** EPIC 6 — Historical Universe Engine
- **Depends on:** QNT-037/038/039 (DONE)

## Problem
The FTSE 250 cross-universe holdout (QNT-115) needs `members("FTSE250", date, as_of)`
over genuinely historical membership. EODHD's FTMC.INDX carries current components only
(verified 2026-08-16, payload archived), so the curated-history machinery that built
FTSE 100 must be extended. FTSE 250 churn is several times FTSE 100's, and the
100↔250 boundary is the danger zone: promotions/demotions are index transfers, never
delistings or new identities.

## Objective
Versioned, provenance-cited FTSE 250 membership history ingested through the QNT-037
schema; a permanent gate asserting FTSE100 ∩ FTSE250 = ∅ at every date under the
effective-date convention; documented conventions (changes take effect at the index
effective date — the next trading session after the review implementation, which is
what an investor could actually trade).

## Scope
- Curated history file (same contract as ftse100_history.json) with anchor + change
  events, every entry cited; needs_verification flags where sources disagree.
- Security-master extension for new (non-FTSE-100) companies; promotions/demotions
  resolve to EXISTING security ids (asserted in tests).
- Membership written via write_universe under universe="FTSE250"; replay validation.
- Overlap gate in tests/gate (monthly grid over coverage).
- Price/action backfill for new members via the QNT-091 pipeline.

## Acceptance criteria
- [ ] members("FTSE250", d, as_of) live over the covered span; entrants/exits/
      promotions/demotions/acquisitions/failures preserved; at least one known
      promotion and demotion hand-asserted (same security_id on both sides).
- [ ] FTSE100 ∩ FTSE250 = ∅ gate green at every monthly date; any source-date overlap
      resolved explicitly in the curated file, not deduplicated silently.
- [ ] Dataset versioned; provenance and adjudications documented; coverage report
      generated (QNT-112 consumes it).

## Completion notes
_In progress._
