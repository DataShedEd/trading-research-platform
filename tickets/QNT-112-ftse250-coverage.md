# QNT-112 — FTSE 250 research coverage and missing-history remediation

- **Ticket ID:** QNT-112
- **Status:** BACKLOG
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
- [ ] Per-year coverage table committed; research start decision logged as a DEC entry.
- [ ] Every accepted exception enumerated with category and evidence.
- [ ] Gate enforces completeness within coverage minus exceptions.

## Completion notes
_Not started._
