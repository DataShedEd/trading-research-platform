# QNT-105 — Source the DEC-016 missing histories (finite remediation list)

- **Ticket ID:** QNT-105
- **Status:** BACKLOG
- **Priority:** P3
- **Epic:** EPIC 3 — Market Data
- **Depends on:** DEC-016, DEC-025

## Problem
Sixteen ex-FTSE-100 securities are absent from EODHD entirely (SABMiller, Xstrata, ENRC,
ICAP, AMEC, TUI Travel, Worldpay, Invensys, International Power, Autonomy, Friends Life,
Cable & Wireless, Home Retail, African Barrick, Essar, Cadbury), ≈2.5% of member-months
2010–2026. Per DEC-025 this is known survivorship-related missingness with NO claimed
bias direction — most of these names exited via acquisition, so the missingness is
correlated with corporate outcomes, not random.

## Objective
Turn the exclusion list into a finite remediation list: source daily bars, dividends,
splits and exit consideration for the sixteen names from a second provider or primary/
alternative sources, ingest under a distinct source label, and shrink the DEC-016 list.

## Scope
- Candidate sources: LSEG/Refinitiv, Bloomberg one-off export, WRDS/Compustat Global,
  Stooq/investing archives, issuer/LSE historical records. Document licensing and cost
  per candidate before purchase (owner gate).
- Ingest as a new raw source (append-only), canonicalise through the existing repair
  pipeline, cross-validate overlapping names against EODHD before trusting.
- Each remediated name is removed from `KNOWN_DATA_GAPS`; the QNT-041 gate re-greens
  with the shrunken list (the list may only shrink — DEC-016 rule preserved).
- Re-run the frozen baselines on the extended store as a NEW dataset version and report
  the delta — this measures the actual (currently unquantified) missingness effect.

## Acceptance criteria
- [ ] Sourcing report with per-name coverage and cost; owner sign-off before spend.
- [ ] Ingested names pass the same unit-repair and validation gates as EODHD data.
- [ ] DEC-016 list shrinks; delta report quantifies the missingness effect on the
      momentum baseline.

## Completion notes
_Not started._
