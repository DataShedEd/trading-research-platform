# QNT-014 — Corporate action canonical schema

- **Ticket ID:** QNT-014
- **Status:** BACKLOG
- **Priority:** P1
- **Epic:** EPIC 3 — Market Data

## Problem
Corporate actions are where price history goes wrong. A split stored as a decimal ratio, a dividend
without its currency, or an ex-date confused with a pay date each produce returns that look
reasonable and are wrong by exactly the size of the event. Providers disagree on all three.

## Objective
Canonical domain models for every corporate action type the platform handles, with exact term
representation — ratios as exact fractions, amounts as `Decimal` with an explicit currency — and an
`available_at` timestamp so that adjustments can themselves be queried point-in-time.

## Scope
`src/trp/domain/corporate_actions.py` defining a discriminated union over action types:
split/consolidation, ordinary dividend, special dividend, rights issue, merger/acquisition,
delisting, and ticker change. Common fields: `security_id`, `action_type`, `ex_date`, `record_date`
and `pay_date` where known, `source`, `available_at`, `available_at_imputed`. Per-type terms as
below. Unit tests per action type.

Terms per type:

- **Split / consolidation** — ratio as an exact `Fraction` (2-for-1 is 2/1; a 1-for-10
  consolidation is 1/10), never a rounded decimal.
- **Dividend / special dividend** — amount as `Decimal` plus currency and quotation unit; a flag
  distinguishing ordinary from special.
- **Rights issue** — subscription ratio as a `Fraction`, subscription price as `Decimal` plus
  currency.
- **Merger / acquisition** — consideration as cash amount, share exchange ratio, or both;
  acquirer reference where known.
- **Delisting** — reason enum, last trading date.
- **Ticker change** — old and new ticker, exchange.

## Out of scope
Computing adjustment factors or adjusted prices (QNT-015), applying events to the security master
(QNT-010 — this ticket models the market-data record, which QNT-010's helpers may consume), provider
ingestion, rights-issue theoretical ex-rights pricing.

## Acceptance criteria
- [ ] Each action type is a frozen Pydantic v2 model in a discriminated union keyed on
      `action_type`; parsing a record with an unknown type raises rather than falling back to a
      generic action.
- [ ] Split and rights ratios are stored as exact fractions (numerator and denominator integers) and
      a test asserts that a 1-for-3 consolidation round-trips without becoming `0.3333…`.
- [ ] Every monetary amount carries an explicit currency and quotation unit; a dividend without a
      currency fails construction.
- [ ] `ex_date` is mandatory for splits, dividends, and rights issues; `record_date` and `pay_date`
      are optional and validated to be on or after `ex_date` when present.
- [ ] Every record carries `available_at` as a timezone-aware UTC timestamp; where the source gives
      none it is imputed conservatively per DEC-007 and `available_at_imputed` is set.
- [ ] Unit tests cover the term representation of each of the seven action types with a realistic
      worked example, including a special dividend distinguished from an ordinary one.

## Technical notes
Ratios as `Fraction` rather than `Decimal` is deliberate: a 1-for-3 consolidation has no exact
decimal representation, and the cumulative product over several events in QNT-015 must be exact.
Serialise fractions to Parquet as a numerator/denominator integer pair rather than as a string or a
float, so the exactness survives storage.

Ordinary versus special dividends matter beyond bookkeeping: providers frequently include specials
in their adjusted-close series and frequently omit them from dividend feeds, so the distinction is
needed both for total-return calculation and for reconciling against a provider's own adjusted
prices in QNT-015.

Ex-date is the adjustment date — the first date the price trades without entitlement — and is the
only date the adjustment engine uses. Record and pay dates are retained for accounting and for
reconciliation, and their optionality reflects that many providers omit them for older history.

`available_at` on corporate actions is what allows QNT-015's factors to be computed as at a
knowledge date rather than with hindsight, and it is why a provider's late-published dividend cannot
retroactively change a backtest's returns. Follow the DEC-007 imputation direction: late, flagged,
documented.

The delisting and ticker-change types overlap conceptually with QNT-010's security master events.
Keep them as market-data records here and let QNT-010's helpers consume them, rather than
duplicating the lifecycle logic.

## Dependencies
QNT-006 — supplies `security_id`, the enum conventions, and the domain package layout.

## Risks
Provider disagreement on ratio direction (2-for-1 versus 1-for-2 for the same event) will produce
inverted adjustments. Mitigated by documenting the convention unambiguously in the model docstring,
naming fields so the direction is explicit, and validating in QNT-015 against a hand-computed
price-continuity check at the ex-date.

## Testing requirements
`tests/domain/test_corporate_actions.py`. One worked example per action type; a fraction-exactness
test; a date-ordering test; an imputation test asserting the flag and the conservative direction.
Time-travel coverage lands in QNT-015 where the factors are consumed as at a knowledge date, and the
fixtures here must be shaped for reuse there.

## Documentation requirements
`docs/DATA_MODEL.md` `corporate_actions` section expanded with the per-type term representation and
the ratio direction convention.

## Completion notes
_Not started._
