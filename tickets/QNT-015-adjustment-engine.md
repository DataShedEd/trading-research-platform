# QNT-015 — Adjustment factor engine

- **Ticket ID:** QNT-015
- **Status:** BACKLOG
- **Priority:** P1
- **Epic:** EPIC 3 — Market Data

## Problem
Raw prices are discontinuous across splits and dividends. Every factor, return, and backtest depends
on adjusting for those events correctly, and the common shortcut — overwriting price history with a
provider's adjusted series — destroys the as-traded record, makes the adjustment unauditable, and
changes historical values whenever the provider revises its series.

## Objective
Derive cumulative split and dividend adjustment factors per security and date from corporate-action
records, store the factors as data, and compute adjusted prices and total returns from raw prices
and factors — leaving the raw record untouched.

## Scope
`src/trp/derived/adjustments.py` providing:

- `compute_adjustment_factors(bars, actions, *, as_of) -> AdjustmentFactorFrame` producing, per
  `security_id` and date, a cumulative split factor and a cumulative dividend (total-return) factor
- `adjusted_prices(bars, factors)` and `total_returns(bars, factors)`
- persistence of `adjustment_factors` under `data/derived/` with the versions of its inputs recorded

Worked numeric fixtures for a 2-for-1 split, a 1-for-5 consolidation, an ordinary dividend, and a
special dividend.

## Out of scope
Rights-issue adjustment (deferred until data quality supports it — record the gap explicitly),
FX conversion of dividends (QNT-017 supplies the interface), factor computation (Epic 5), backtest
accounting for delisting proceeds (Epic 6).

## Acceptance criteria
- [ ] Cumulative factors are computed backwards from the most recent date so that the latest date
      has a factor of exactly 1, and applying them to raw prices reproduces the standard adjusted
      series; the convention is stated in the module docstring.
- [ ] A 2-for-1 split fixture: the adjusted return across the ex-date equals the hand-computed
      value, and the raw bars are byte-identical before and after the computation.
- [ ] A 1-for-5 consolidation fixture produces exact factors with no rounding drift, verified by
      asserting the `Fraction`-derived factor rather than a float approximation.
- [ ] An ordinary-dividend fixture: the price return and the total return across the ex-date differ
      by exactly the hand-computed dividend yield, and a special-dividend fixture is handled by the
      same path with its special flag preserved in the output provenance.
- [ ] Two events on the same ex-date (a split and a dividend) compose in a documented, tested order
      producing the hand-computed result.
- [ ] `compute_adjustment_factors` requires `as_of` and excludes corporate actions with
      `available_at > as_of`; stored factors carry the source data versions and ingestion timestamps
      of their inputs, so a result can be regenerated per `docs/QUANT_PRINCIPLES.md` §4.

## Technical notes
Arithmetic is `Decimal` and `Fraction` throughout the factor derivation (DEC-005); conversion to
float happens only at the derived-analytics boundary where vectorised performance matters, and that
boundary must be a single explicit function rather than scattered casts.

The split factor is the cumulative product of the ratios of all splits on or after a date. The
dividend factor uses the standard `1 - D / P_prev_close` form, where `P_prev_close` is the raw close
on the last trading day before the ex-date — which requires the trading calendar, so guard the case
where the previous close is missing rather than silently reaching further back.

Storing factors rather than adjusted prices is the requirement from `docs/DATA_MODEL.md`: adjusted
prices are computed, raw and adjusted are always distinguishable, and no in-place mutation ever
occurs. Recomputing factors after an ingestion produces a new factor set; do not overwrite the old
one where a research result references it.

Where a provider supplies its own adjusted close (retained by QNT-013 as a cross-check), reconcile
against it and report the discrepancies as a diagnostic. Disagreement is common and usually means
the provider treats specials differently — the reconciliation report is valuable precisely because
it is not always clean, so do not tune our factors to match the provider's.

Rights issues are deliberately deferred; make the omission explicit in the output provenance so a
security with a rights issue in its history is flagged rather than quietly mis-adjusted.

## Dependencies
QNT-013 — supplies the raw bars the factors apply to.
QNT-014 — supplies the corporate-action records the factors derive from.

## Risks
An inverted split ratio produces a factor that is wrong by the square of the ratio and still looks
like a plausible price series. Mitigated by the price-continuity check at ex-dates: an adjusted
close that jumps by roughly the split ratio across the ex-date indicates an inversion, and this
check belongs in the fixture assertions as well as QNT-019's report.

## Testing requirements
`tests/derived/test_adjustments.py` with hand-computed numeric fixtures for each of the four named
events plus the same-date composition case, and
`tests/timetravel/test_adjustments_timetravel.py` (pytest marker `timetravel`) asserting that a
dividend with a later `available_at` does not affect factors computed as at an earlier `as_of`.
Expected values must be derived by hand and shown in the fixture, not copied from the
implementation's output.

## Documentation requirements
`docs/DATA_MODEL.md` `adjustment_factors` section updated with the factor definitions and the
normalisation convention. A `RESEARCH_METHODOLOGY.md` note (or a `DECISIONS.md` entry) recording the
deferral of rights-issue adjustment and its effect on affected securities.

## Completion notes
_Not started._
