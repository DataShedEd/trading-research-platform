# QNT-034 — Corporate-action and price accuracy checks

- **Ticket ID:** QNT-034
- **Status:** BACKLOG
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
- [ ] Each of the five check families above is implemented against the QNT-029 protocol, declares
      the dataset kinds and awkward properties it applies to, and returns `not applicable` (never
      `pass`) for a security to which the expectation does not apply.
- [ ] Every check result carries evidence sufficient to adjudicate it without re-fetching: expected
      value, observed value, the security and date concerned, and a reference to the raw payload
      that produced the observation.
- [ ] Numeric comparisons use `Decimal` with an explicit, documented tolerance per check family —
      exact for split ratios and dates, a stated tolerance for prices and dividend amounts — and a
      unit mismatch (pence versus pounds) is reported as a distinct failure reason rather than as
      a factor-of-100 numeric discrepancy.
- [ ] The delisted-history check tests presence of data through to the delisting date and reports
      the observed final trading date and the shortfall in days, so partial coverage is
      distinguishable from total absence in the results.
- [ ] The raw-versus-adjusted check reconstructs adjusted prices from the provider's own raw prices
      and corporate actions and reports the reconciliation error, failing when the provider's
      adjusted series cannot be explained by its own action records.
- [ ] All checks run end to end against the fake provider in tests, with fixtures covering a
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
_Not started._
