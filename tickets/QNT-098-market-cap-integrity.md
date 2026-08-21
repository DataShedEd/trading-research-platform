# QNT-098 — Market-cap integrity: dated share counts and price-currency classification

- **Ticket ID:** QNT-098
- **Status:** DONE
- **Priority:** P1
- **Epic:** EPIC 3 — Market Data Core

## Problem
The factor_panel surfaced implausible valuation ratios for a handful of names, and the
diagnosis found two data faults feeding point-in-time market values:
1. **Balance-sheet share counts are unreliable** — EODHD's `commonStockSharesOutstanding`
   for Shell reads 1.62bn against a true ~7.9bn (pre-consolidation ~a fifth of reality),
   inflating Shell's earnings yield ~5x. Meanwhile the top-level `outstandingShares`
   dated series is correct (Shell 2024: 6.21bn) AND is on the same share basis as
   EODHD's price series even where that basis is retroactively consolidated (Capita
   ~117m at 15:1, Hammerson ~490m at 10:1) — so price x dated-shares is right precisely
   where balance-sheet counts and prices individually look wrong.
2. **Some price series are in currencies the GBX/GBP repair never contemplated** —
   Ferguson's whole series is ~$82-scale USD (dividends USD-labelled, USD yield ~2.5%
   sane), read as GBX it produces a 472% earnings yield.

## Objective
Market caps built from the dated share series; a validation harness that flags every
implausible FTSE-member market cap month; price-currency classification or adjudication
for every flagged name; value factors re-materialised clean.

## Scope
- Canonicalise `outstandingShares` (raw payloads already archived) into
  `data/canonical/shares/` with conservative availability (entry date + 30 days —
  share counts are public via RNS within days; the lag is the DEC-007 safe direction).
  Entries dated in the future (vendor projections) are dropped.
- `market_value_yield` uses the dated series for shares; balance-sheet
  `shares_outstanding` remains for accounting ratios only.
- Bar-currency support in market values: a repaired bar whose currency is USD/EUR
  converts at the dated FX rate like fundamentals do.
- Validation harness: mcap per member-month; flag < GBP 200m or > GBP 350bn while a
  FTSE 100 member; classify/adjudicate every flagged security with evidence.

## Acceptance criteria
- [x] Shell/Ferguson/Capita/Hammerson-class mcaps land in plausible ranges, evidenced by
      the harness before/after.
- [x] The harness reports zero unadjudicated implausible member-months, or each residual
      is listed with a written reason.
- [x] Value-factor gate medians stay in FTSE territory; timetravel suites stay green
      (the shares series respects its availability convention).
- [x] Re-materialised factor store and refreshed factor_panel.

## Dependencies
QNT-097 (payloads), QNT-093 (unit repair), QNT-046 (market_value_yield).

## Risks
The dated series may itself be revisionist (vendor-maintained); its 30-day lag is an
approximation of RNS timing, documented. Residual basis mismatches (a price basis
changing where the share series does not) are exactly what the harness exists to catch.

## Completion notes
2026-08-21. Root causes found and fixed with evidence throughout. (1) Dated shares:
`trp.canonical.shares` canonicalises EODHD's top-level outstandingShares (16,882 rows,
170 securities, entry date + 30d DEC-007-style availability, vendor projections
dropped) with a continuity guard that rescued 93 same-digits /100-/1000 vendor glitches
(Meggitt 7,820,200 -> 782,020,000 class) — real consolidations (max ~15:1) cannot trip
the 20x gate. market_value_yield uses this series (balance-sheet counts remain for
accounting ratios, flagged when used as fallback); Shell's earnings yield deflated ~5x
to sanity. (2) Price currency: PRICE_CURRENCY_OVERRIDES relabels Ferguson (USD-quoted
series, ~GBP 12bn mcap restored) and Metlen (EUR); `_close_gbp_on_or_before` converts
non-GBX bars at the dated FX rate. (3) MARKET_VALUE_EXCLUSIONS: Tullow, Melrose,
Randgold and Capita have era-dependent price bases no single reading rescues — their
market-value factors are typed no_data with the evidence in the warning (composites
renormalise); the DEC-016 rule applies (list may only shrink). The harness
(`validate_market_caps`) is now a gate test: ZERO unadjudicated implausible member-months
(128 flagged, all on the documented list). Value factors + qvm_equal re-materialised
(1,400 files); factor gate medians unchanged (FTSE territory); 820 default + 22 gate
green. KNOWN FOLLOW-UPS recorded: Melrose's x100-repaired price level also inflated its
weight in the momentum tearsheet (ratios fine, sizing distorted) — re-run the tearsheet
after a segment-level Melrose re-adjudication; consider a second-vendor spot-check for
the four excluded names.
