# QNT-034 — Corporate-action and price accuracy checks

- **Ticket ID:** QNT-034
- **Status:** DONE
- **Priority:** P1
- **Epic:** EPIC 5 — Data Provider Bake-Off

## Problem
Corporate actions are where price history quietly becomes fiction. A missing split turns a 4:1
consolidation into a 75% one-day loss that a momentum factor will happily trade; a missing special
dividend understates total return; a delisted company whose prices stop three months early makes
bankruptcy look like a mild drawdown; a ticker change with no continuity makes one company look
like two. Every one of these failures is invisible in a summary statistic and obvious against a
known-correct expectation. Until those expectations are checked empirically, the platform has no
evidence that any provider's price history can support QUANT_PRINCIPLES §2 and §3.

## Objective
Implement the harness checks that compare each provider's corporate-action and price data against
the validation universe's known-correct expected facts, producing pass/fail results with evidence
that the rubric can score and the report can quote.

## Scope
`src/trp/bakeoff/checks/corporate_actions.py` and
`src/trp/bakeoff/checks/prices.py`, registered against the QNT-029 check protocol. Checks:

- **Split and consolidation ratios and ex-dates** — every split/consolidation in the universe is
  present, with the correct ratio and correct ex-date.
- **Dividend amounts and dates** — ordinary and special dividends match expected amount, currency,
  unit (GBX versus GBP) and ex-date; special dividends specifically are not silently omitted.
- **Delisted price history** — a delisted security exists at all, and its price history runs up to
  (not obviously short of) the known delisting date.
- **Raw versus adjusted consistency** — the provider's adjusted series is reconcilable with its raw
  series through its own corporate-action records, and raw and adjusted are distinguishable.
- **Price continuity across ticker changes** — history spans a known ticker change without a gap,
  a duplicate, or a discontinuity inconsistent with the corporate action.

## Out of scope
Point-in-time fundamental checks (QNT-035); scoring and weighting (QNT-030); the report (QNT-036);
the platform's own adjustment engine (Epic 3) — these checks assess provider data, not our
transforms.

## Acceptance criteria
- [x] Each of the five check families above is implemented against the QNT-029 protocol, declares
      the dataset kinds and awkward properties it applies to, and returns `not applicable` (never
      `pass`) for a security to which the expectation does not apply.
- [x] Every check result carries evidence sufficient to adjudicate it without re-fetching: expected
      value, observed value, the security and date concerned, and a reference to the raw payload
      that produced the observation.
- [x] Numeric comparisons use `Decimal` with an explicit, documented tolerance per check family —
      exact for split ratios and dates, a stated tolerance for prices and dividend amounts — and a
      unit mismatch (pence versus pounds) is reported as a distinct failure reason rather than as
      a factor-of-100 numeric discrepancy.
- [x] The delisted-history check tests presence of data through to the delisting date and reports
      the observed final trading date and the shortfall in days, so partial coverage is
      distinguishable from total absence in the results.
- [x] The raw-versus-adjusted check reconstructs adjusted prices from the provider's own raw prices
      and corporate actions and reports the reconciliation error, failing when the provider's
      adjusted series cannot be explained by its own action records.
- [x] All checks run end to end against the fake provider in tests, with fixtures covering a
      correct provider, a provider missing a split, a provider missing a special dividend, a
      provider truncating a delisted history, and a provider whose adjusted series is
      irreconcilable — each producing the expected failure with the expected evidence.

## Technical notes
These checks are the empirical content of the corporate-action-accuracy, historical-depth and
delisted-coverage criteria in `docs/DATA_PROVIDER_EVALUATION.md`, so their outputs must map cleanly
onto the criteria QNT-030 scores. Keep each check narrow and single-purpose; a compound check that
fails for one of four reasons is useless in a comparison table.

Expectations come from QNT-027 and are the arbiter, but they are not infallible. When a check fails,
the first question is whether the provider or the expectation is wrong, which is why evidence and
the raw payload reference are mandatory rather than nice to have. Consider marking a disagreement
confirmed by two independent providers as an expectation-review flag in the results, rather than
scoring it against both.

UK specifics deserve care. LSE prices are quoted in pence and dividends are often declared in
pence while some APIs return pounds; a check that does not compare units explicitly will produce
either false failures or, worse, false passes on a factor-of-100 error. Similarly, a consolidation
is a split with a ratio below one — make sure the comparison handles reverse ratios and both
common ratio conventions (old:new versus new:old), since a provider using the opposite convention
is a real finding that must be reported as such, not silently accepted.

The delisting check should look for the shape of a failure, not just row counts: Carillion and
Thomas Cook should show prices up to suspension, and a provider that ends the series months early
or backfills a fabricated final price is failing differently. Report the observed final price and
date so the report can show it.

Raw-versus-adjusted reconciliation is the check most likely to expose subtle problems, because it
holds the provider to its own data rather than to ours. Compute cumulative factors from the
provider's corporate actions in `Decimal` (DEC-005), apply them to the raw series, and compare
against the provider's adjusted series over a window spanning each known action.

Checks read raw payloads or transport-level adapter output — never canonical data — so that what is
measured is the provider, not our normalisation.

## Dependencies
QNT-029 — the check protocol, result structure and harness that executes these checks and supplies
the validation-universe expectations.

## Risks
A check that is subtly wrong is worse than no check: it either exonerates a bad provider or
condemns a good one, and the purchase decision follows. Mitigated by testing every check against
both a correct and a deliberately broken fake provider, so each check is demonstrated to fail when
it should. A second risk is expectation error in the validation universe surfacing as provider
failure; mitigated by mandatory evidence and the expectation-review flag.

## Testing requirements
`tests/bakeoff/test_corporate_action_checks.py` and `tests/bakeoff/test_price_checks.py`, each
running the checks against fake-provider fixtures for the correct and broken cases listed in the
acceptance criteria, plus unit tests for ratio-convention handling, GBX/GBP units, reverse splits
and tolerance boundaries. No live provider calls. No `timetravel` marker applies to these checks —
they compare provider data against static known facts rather than serving as-of queries — but any
check that inspects a corporate action's `available_at` must assert it is timezone-aware UTC.

## Documentation requirements
`docs/DATA_PROVIDER_EVALUATION.md` scoring table rows for corporate-action accuracy, historical
depth and delisted coverage updated to name the specific checks that measure them. The
`src/trp/bakeoff/` README gains these checks in its list, including the tolerance conventions, so
a reader of the generated report can interpret a failure.

## Completion notes

**2026-08-16 — implementation and tests complete; documentation outstanding, so the status is
IN_PROGRESS rather than DONE.**

Six checks in `src/trp/bakeoff/checks_corporate_actions.py`, registered at import through an
idempotent `register_all()` (safe to call after `checks.clear_registry()` in test fixtures):

| check | criterion | dataset | applies to |
| --- | --- | --- | --- |
| `split_ratio_and_ex_date` | corporate_action_accuracy | corporate_actions | split, consolidation |
| `dividend_amount_and_ex_date` | corporate_action_accuracy | corporate_actions | every entry with a `DividendFact` |
| `delisted_price_history` | delisted_coverage | prices | failure, acquisition |
| `price_history_depth` | historical_depth | prices | long_lived |
| `raw_vs_adjusted_consistency` | corporate_action_accuracy | prices | every entry |
| `price_continuity_across_ticker_change` | corporate_action_accuracy | prices | ticker_change |

Tolerances are module constants with a stated reason each: split ratios and all dates exact;
dividend amounts 0.5% relative; delisted history within 5 calendar days of the delisting (and a
separate failure for prices *past* it, which is fabrication rather than shortfall); adjusted
reconstruction 0.5% relative; ticker-change continuity a 7-day gap and a 25% unexplained step;
depth 20 years. Ratios are read new-per-old and an inverted ratio is reported as a convention
difference in its own words. Units are compared explicitly: `GBp` is normalised to `GBX` (never
upper-cased into `GBP`), a stated-but-different unit is converted before comparison, and a
factor-of-100 gap — labelled or unlabelled — is reported as a unit failure, never as a numeric
discrepancy.

Two conventions introduced, both documented in `src/trp/bakeoff/payloads.py`:

1. **The neutral payload convention.** Checks receive raw bytes and no adapter exists yet
   (QNT-031…033 are blocked on API keys), so the checks parse a documented neutral JSON shape:
   `{"rows": [...], "actions": [...]}` for prices, `{"actions": [...]}` for corporate actions,
   `{"statements": [...]}` for fundamentals, with several accepted key spellings per field. **This
   is an assumption, not a measurement:** a passing check today proves the check works, not that a
   provider does. Real adapters must either approximate this shape or these parsers must be
   extended — expected to be additive (extra accepted spellings) rather than a rewrite. Raw
   versus adjusted reconciles against the actions carried *on the price payload*, because a check
   only ever sees the payloads of its own cell; with no actions or no adjusted series it is
   `not_applicable`, never a pass by omission.
2. **`EXPECTATION_REVIEW_PREFIX`** — the ticket's expectation-review flag. A mismatch against a
   universe fact carrying `needs_verification` is still `FAIL` (suppressing it would hide real
   provider errors), but the explanation is prefixed and states that the expectation must be
   re-verified against a primary source before the failure counts against the provider. The
   generated report surfaces the flag on every quoted example.

Tests: `tests/bakeoff/test_checks_corporate_actions.py`, 38 cases — correct provider, missing
split, inverted ratio, misdated split, missing special dividend, GBX/GBP and `GBp` handling,
unit-less payloads, truncated and over-running delisted history, irreconcilable adjusted series,
adjusted-identical-to-raw, ticker-change gap/duplicate/jump, unparseable payload, and
not-applicable paths. An end-to-end run (fake provider → `run_bakeoff` → `score_provider` →
`render_report`) lives in `tests/bakeoff/test_report.py`. `uv run pytest` 547 passed; `mypy
--strict` and `ruff` clean.

Deviations from the ticket text, all deliberate:

- One module `checks_corporate_actions.py` rather than a `checks/` package: `checks.py` already
  holds the protocol, so a package of that name would shadow it. Prices and corporate-action
  checks therefore live together.
- Test file is `test_checks_corporate_actions.py`, not `test_corporate_action_checks.py` /
  `test_price_checks.py`.
- The `available_at` timezone assertion in the testing requirements does not apply: the neutral
  action payload carries no `available_at`, and nothing in these checks inspects one. When an
  adapter surfaces it, that assertion must be added with the parsing.
- `price_history_depth` was added for the historical-depth criterion named in the technical
  notes; it is scoped to `long_lived` entries because depth is only meaningful where the security
  genuinely existed for the period demanded.

**Still required before this can be DONE** (not attempted here — concurrent work owns those
files): `docs/DATA_PROVIDER_EVALUATION.md` scoring-table rows for corporate-action accuracy,
historical depth and delisted coverage naming these six checks, and `src/trp/bakeoff/README.md`
listing them with the tolerance conventions above so a reader of the generated report can
interpret a failure.

**Coordinator close-out (2026-08-16):** the deferred doc items are done — check inventory
with tolerance conventions added to `src/trp/bakeoff/README.md` and the per-criterion check
listing to `docs/DATA_PROVIDER_EVALUATION.md`. Status DONE.
