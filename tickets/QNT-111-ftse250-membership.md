# QNT-111 — FTSE 250 historical membership + overlap gate

- **Ticket ID:** QNT-111
- **Status:** DONE
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
- [x] members("FTSE250", d, as_of) live over the covered span; entrants/exits/
      promotions/demotions/acquisitions/failures preserved; at least one known
      promotion and demotion hand-asserted (same security_id on both sides).
- [x] FTSE100 ∩ FTSE250 = ∅ gate green at every monthly date; any source-date overlap
      resolved explicitly in the curated file, not deduplicated silently.
- [x] Dataset versioned; provenance and adjudications documented; coverage report
      generated (QNT-112 consumes it).

## Completion notes
See DEC-026 for the full sourcing decision. Highlights:
- Official FTSE Russell constituent-history PDF parsed positionally (1,034 rows;
  a first-pass parser bug dropping single-digit-day rows was caught by cross-checking
  Burberry/Royal Mail against the validated FTSE 100 history and fixed to
  refuse-not-drop); June 2025 + June 2026 reviews from LSEG releases (two-column
  interleaved tables de-interleaved and count-verified).
- End anchor = Wikipedia 2026-08-20 (validated against the June 2026 review);
  EODHD FTMC components REJECTED (internally inconsistent). 26 dated Wikipedia
  snapshots 2013–2025 as replay checkpoints; look-ahead confirmation suppresses
  transient wiki staleness; self-healing auto-aliases for label drift.
- Documented errata corrected with citations (duplicate Provident/Royal Mail row,
  Hvve/Reinshaw/Utilco typos, Hipgnosis C-line conversion); ~120 rename/label aliases,
  every one annotated; sanctioned exits (Evraz/Polymetal) and NMC dated ad-hoc.
- Identity: 664 companies → 618 resolved (134 to EXISTING FTSE 100 master ids —
  promotions/demotions never mint identities, gate-asserted with Royal Mail 2018 and
  Burberry 2024); 484 new securities minted; 16 EODHD-absent (provisional exception
  list, may only shrink, no bias direction claimed per DEC-025); 46 pre-2013-only
  unresolved (logged, outside checkpoint support).
- 861 membership spells written under universe=FTSE250; reconciliation ledger: 41
  checkpoint-dated boundaries flagged '[unverified]' (~0.26% of member-months, each
  bounded by adjacent snapshots).
- Gates (tests/gate/test_ftse250_gate.py): overlap ∅ at ~165 monthly dates, counts
  244–253, promotion/demotion identity, survivorship (Carillion in June 2017).
