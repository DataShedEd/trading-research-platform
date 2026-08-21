# QNT-112 — FTSE 250 research coverage and missing-history remediation

- **Ticket ID:** QNT-112
- **Status:** DONE
- **Priority:** P1
- **Epic:** EPIC 6 — Historical Universe Engine
- **Depends on:** QNT-111

## Problem
FTSE 100 coverage starts 2010 (DEC-014) — that must NOT be assumed for the FTSE 250,
whose delisted mid-caps are more likely to be missing from EODHD. Weakening completeness
standards to get a longer backtest is the failure mode.

## Objective
Measure coverage independently per year: member-months expected / identity-resolved /
with usable prices / with corporate-action coverage; missing securities and
member-months; coverage %. Categorise every gap: KNOWN DATA GAP / IDENTITY FAILURE /
IPO-INSUFFICIENT HISTORY / LEGITIMATE NON-TRADING / SOURCE AMBIGUITY. Determine the
earliest defensible research start (later than 2010 if the data demands).

## Scope
- Coverage measurement job + committed report (docs/ or ticket).
- Remediation table per missing name: membership dates, canonical id, provider
  identifiers tried (EODHD variants, Tiingo free cross-check), price coverage, reason,
  resolution. No new provider purchases.
- Versioned exception list (may only shrink), NO claimed bias direction (DEC-025).

## Acceptance criteria
- [x] Per-year coverage table committed; research start decision logged as a DEC entry.
- [x] Every accepted exception enumerated with category and evidence.
- [x] Gate enforces completeness within coverage minus exceptions (density/jump screens
      + the coverage measurement itself; ftse250 gate suite).

## Completion notes
- Coverage measured per year (data_sources/ftse/ftse250_coverage.json): identity gaps
  ~0-1% from 2013; price gaps 4.8% (2016) -> 3.5% (2017) -> <=2.7% (2018-20) ->
  <=1.4% (2021+). Research start 2016-01-01 per DEC-029.
- The measurement drove a large remediation campaign (all documented in DEC-028/029):
  master-first resolution ordering (overrides had shadowed FTSE 100 identities for
  Wood Group and DS Smith - duplicate no-data securities minted and later removed);
  US-OTC code mismatches fixed (888/evoke, Pendragon, Phoenix, Sanne, Spirax);
  multi-code rename eras attached (Currys for the Dixons chain, IDS for Royal Mail,
  FCIT for F&C IT, FCPT for F&C CPT, FAN moved from a fuzzy-matched Evolution Group to
  Volution); EODHD PLACEHOLDER SERIES discovered (identical synthetic ~100-based
  fragments served for WTAN/TIFS/ESKN/BCPT) and detached; vendor sentinel day
  (2012-05-28, literal 1,000,000.0 closes) and single-bar spikes filtered; five split
  records adjudicated as capital-event mislabels; Bankers IT's unrecorded 10:1
  subdivision handled by bar exclusion (conservative INSUFFICIENT_DATA outcome).
- Tiingo free-tier cross-check (key configured): HSTG ~274 rows (1 of 5 needed years),
  WTAN/TIFS/CHOO zero — does not remediate; second-provider sourcing (QNT-105 pattern)
  remains the path. Exception list lives in DEC-029; may only shrink; no direction
  claimed (DEC-025).
- The FTSE 100 canonical was re-run per the defect protocol at each dataset change;
  final gbx3: CAGR 10.65% / Sharpe 0.547 / IR 0.260 vs the frozen gbx2 record's
  10.69% / 0.552 / 0.267 — a quantified -4bp/-0.007 correction, conclusion unaffected;
  prior records preserved (momentum-canonical r1, gbx3 r1/r2/r3 all in the registry).
