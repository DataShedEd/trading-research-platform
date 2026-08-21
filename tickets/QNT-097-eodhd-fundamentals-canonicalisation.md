# QNT-097 — EODHD fundamentals backfill and canonicalisation (FTSE-100-ever)

- **Ticket ID:** QNT-097
- **Status:** DONE
- **Priority:** P1
- **Epic:** EPIC 4 — Fundamental Data Core

## Problem
Epic 4's machinery (taxonomy, normalisation, revisions, storage, as-of queries) is DONE but
holds no data beyond bake-off samples: the raw archive has 15 fundamentals payloads and the
EODHD mapping table is provisional throughout — written from documentation, explicitly
banned for factor use until verified against captured JSON. Value and quality factors
(QNT-045/046) are blocked on real, verified, canonicalised fundamentals.

## Objective
Fetch fundamentals for every FTSE-100-ever security through the raw-first pipeline, verify
the EODHD mapping entries against the captured payloads (promoting only what the evidence
supports), and canonicalise into the QNT-024 store with DEC-007 conservative availability
imputation — EODHD's UK filing_date is a period-end default for ~99% of rows, so imputation
is load-bearing.

## Scope
`src/trp/canonical/fundamentals/ingest_eodhd.py`: backfill CLI (paced, idempotent per
archive); payload → ProviderLineItem extraction (Income_Statement/Balance_Sheet/Cash_Flow x
yearly/quarterly, per-row reporting currency, string-decimal values, nulls dropped);
DEC-007 availability (real filing_date used only when it is meaningfully after period_end;
otherwise period_end + documented UK lag — 120 days annual, 90 days interim); mapping
verification report (per-entry presence counts and magnitude sanity across all payloads)
driving promotion of `review_status` in `mappings/eodhd.json`; canonicalisation via
`normalise_line_items` -> `to_fundamental_value` -> `write_fundamentals`; coverage report.

## Acceptance criteria
- [x] Raw archive holds a fundamentals payload for every EODHD provider code in the
      security master (or the absence is listed with the security named).
- [x] Every mapping entry marked `verified` is evidenced by the verification report;
      entries without evidence stay provisional and are excluded from canonicalisation.
- [x] Canonical rows carry DEC-007 imputed availability with the rule recorded whenever the
      vendor filing_date is the period-end default; genuine filing dates pass through.
- [x] The as-of query returns sensible values for spot-checked companies (Tesco revenue,
      Shell in USD) and the existing Epic 4 timetravel suites stay green.
- [x] Coverage summary recorded: securities with data, per-statement row counts, unmapped
      provider items ranked by frequency.

## Dependencies
QNT-020..025 (all DONE), QNT-091 (security master provider codes).

## Risks
EODHD restates without revision history (bake-off finding): first ingestion IS the baseline;
earlier originals are unrecoverable, recorded per RESEARCH_METHODOLOGY. Mapping promotion is
judgement against evidence; anything ambiguous stays provisional rather than guessed.

## Testing requirements
`tests/canonical/test_fundamentals_ingest.py` — extraction fixtures (currency per row,
null dropping, string decimals); DEC-007 imputation branch (default filing_date vs genuine);
verification classifier. Gate test for real-data coverage + spot checks.

## Completion notes
2026-08-21. Backfill: 183 fetched + 8 pre-existing = every one of 191 master provider
codes archived (the 6 extra archived symbols are 4 foreign bake-off validation names,
Carillion — FTSE 250, correctly outside our universe — and an old RR. spelling
duplicate). Mapping verification against 197 payloads promoted all 16 mapped entries to
verified (13k-21k rows each at FTSE-scale magnitudes; four cross-currency anchors:
Tesco FY26 GBP, Shell FY25 USD, AstraZeneca USD, Unilever EUR). Two sign findings, both
now encoded and tested: capex is served positive-magnitude in 20,738/20,738 rows so the
doc-derived FLIP is CORRECT, and dividendsPaid needed a NEW flip (98.8% positive vs the
taxonomy's outflow-negative convention) — mapping v1.1. One extraction fix that mattered:
pre-~2023 rows carry no per-row currency_symbol; falling back to the statement-level
declaration recovered ~75k rows and took Tesco's annual history to 1986 (FY1986 revenue
£3.36bn — matches reality). Final store: 343,411 records across 179+ securities,
1986-2026, 98.3% DEC-007-imputed (available_at = period_end + 120d annual / 90d interim,
rule recorded per row; genuine filing dates >5 days after period end pass through — the
bake-off's ~99% period-end-default finding confirmed at scale). EODHD's 'quarterly'
bucket is UK half-yearly and is stored as INTERIM. Knowability verified end-to-end:
Tesco's Feb-2020 year is invisible on 1 March and visible at the right magnitude after
the lag. Restatement caveat stands: EODHD is latest-view-only, so this first ingestion is
the revision baseline. Tests: tests/canonical/test_fundamentals_ingest.py (9),
updated provider-mapping suite, tests/gate/test_fundamentals_gate.py (5). 768 default +
14 gate green.
