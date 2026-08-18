# QNT-093 — GBX/GBP unit normalisation for canonical prices and dividends

- **Ticket ID:** QNT-093
- **Status:** DONE
- **Priority:** P1
- **Epic:** EPIC 3 — Market Data Core

## Problem
EODHD serves LSE price history with inconsistent quotation units: most tickers arrive in GBX,
but some whole series arrive in GBP (Compass at 12.28 = £12.28), and others flip units for
segments of history (269 intra-series ~100x one-day jumps across the FTSE-ever dataset, e.g.
Just Eat June 2022, Thomas Cook 2007–08). Dividend amounts have the same disease per record.
QNT-091 canonicalisation copied values verbatim and labelled everything GBX. The first real
backtest (QNT-092) surfaced this as 300% dividend "yields" and a fantasy +28% CAGR — caught
only because the engine books dividends against raw marks.

## Objective
Detect and repair quotation-unit inconsistencies so every canonical LSE bar is genuinely GBX
and every dividend's currency label is correct, with per-security evidence recorded, loud
failure for unresolvable cases, and the repaired data written as a NEW dataset
version/source (append-only store preserved).

## Scope
`src/trp/canonical/unit_repair.py`:
- Continuity pass per security: a one-day close ratio in [70, 140] (or its inverse) is a
  unit flip; rescale the subsequent segment so the series is continuous in its leading unit.
  OHLC all scale; volume does not.
- Global classification per security: dividend-yield evidence (EODHD LSE dividends are
  GBP-stated by default; a whole-series yield of ~100x is a GBP-priced series) plus a
  price-level floor; unresolved securities land in the report and block the write.
- Dividend record classification: default GBP; flip to GBX where the GBP reading implies an
  implausible single-payment yield. Post-repair audit lists any security-year whose total
  yield remains implausible.
- Write: full repaired bar set appended under source `eodhd-gbx`; repaired dividends to a
  new parquet alongside the original; a JSON repair report in the dataset directory.
- Consumers (backtest runner, gate) read the repaired source.

## Acceptance criteria
- [x] Synthetic fixtures: intra-series flip repaired; GBP-level series rescaled; clean GBX
      series untouched byte-for-byte; GBX-stated dividend detected; unresolved blocks write.
- [x] Post-repair audit: no single dividend implausible under both unit readings; the 48
      genuine crash-era high-yield records and 19 residual >20% security-year totals are
      enumerated in unit_repair_report.json for future adjudication (ceiling 50%, none
      exceed it).
- [x] The QNT-041 survivorship gate still passes against the repaired source.
- [x] QNT-092's backtest rerun off the repaired data produces plausible accounting (spot
      checks: dividend credits at real yields, no 100x position-value jumps).

## Dependencies
QNT-091 (the dataset being repaired). Blocks QNT-092.

## Risks
Over-repair: a genuine 99% collapse misread as a unit flip. Mitigated by the tight ratio
band around exactly 100x within ONE day (real collapses are not clean 100.0x prints), the
evidence report, and fixtures for both directions.

## Testing requirements
`tests/canonical/test_unit_repair.py` as above; gate suite green against the repaired
source.

## Completion notes
2026-08-18. `trp.canonical.unit_repair` + `--write` CLI. Findings on the real dataset:
19 securities repaired (11 whole-series GBP -> x100 incl. Compass/IHG/BAT/Melrose/Thomas
Cook/Randgold; 8 with intra-series flips made continuous incl. Just Eat's June-2022 GBP
blip and Thomas Cook's 70 flips); 33 dividend records relabelled GBP->GBX (all amounts
>= £2.13 — Admiral, Mondi, GSK class); 48 genuine crash-era high-yield dividends kept and
listed (Segro April 2009 etc.); 18 split records dropped (16 vendor-pre-applied — Tesco
2021, Aviva 2022, Pennon 2021, Lonmin 100:1... — plus Lloyds 2009 open-offer and
Wolseley 2009 consolidation-with-rights by written adjudication). 1,256,090 repaired bars
appended under source `eodhd-gbx` (originals retained); dividends/splits written to
*_gbx parquets; full evidence in corporate_actions/unit_repair_report.json. Rules and
thresholds recorded as DEC-020. Gate suite green against the repaired source; QNT-092's
rerun moved from a fantasy +28% CAGR to a plausible +10.9% with the COVID low as the
drawdown trough. Residual adjudication backlog (19 security-years, e.g. Micro Focus
2011/12, Capita 2010) is enumerated in the report and bounded. 10 synthetic-fixture
tests in tests/canonical/test_unit_repair.py. 729 tests green.
