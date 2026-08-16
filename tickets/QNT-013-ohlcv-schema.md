# QNT-013 — Canonical daily OHLCV schema

- **Ticket ID:** QNT-013
- **Status:** DONE
- **Priority:** P1
- **Epic:** EPIC 3 — Market Data

## Problem
Providers deliver daily bars in inconsistent shapes: some pre-adjusted, some in mixed quotation
units, some with float prices that lose the last penny. Without a canonical raw-price record with
enforced invariants, adjustment errors and unit errors enter the system at ingestion and are
undetectable afterwards.

## Objective
A domain model and declared Parquet schema for raw, as-traded daily bars, with validation
invariants that reject impossible bars, and an explicit guarantee that adjustments never mutate
these values.

## Scope
`src/trp/domain/prices.py` defining `DailyBar`; the declared PyArrow schema for `prices_daily`;
validation invariants; unit tests.

Fields per `docs/DATA_MODEL.md`: `security_id`, `trade_date`, `open`, `high`, `low`, `close`
(`Decimal`), `volume`, `currency` (quotation unit, `GBX` permitted), `source`, `ingested_at`.
Optional where a provider supplies it: `adjusted_close_provider` retained purely as a cross-check,
never as the platform's own adjusted value.

## Out of scope
Storage layout and partitioning (QNT-018), adjustment factors (QNT-015), calendar-based gap
detection (QNT-016, QNT-019), intraday or tick data, provider ingestion adapters.

## Acceptance criteria
- [x] `DailyBar` is a frozen Pydantic v2 model with `Decimal` OHLC fields, `date` trade date, and a
      timezone-aware UTC `ingested_at`; `mypy --strict` passes.
- [x] Validation rejects `high < low`, `high < open`, `high < close`, `low > open`, `low > close`,
      and negative volume, with an error naming the violated invariant and the offending values.
- [x] Zero or negative prices are rejected; a bar with a zero price is a data error, not a valid
      observation, and must fail construction rather than being coerced.
- [x] `currency` is a validated ISO 4217 code with `GBX` accepted as a documented quotation unit,
      and the model records the quotation unit rather than silently converting it.
- [x] The declared Parquet schema pins `Decimal128` precision and scale for OHLC, an integer type
      wide enough for volume, `date32` for `trade_date`, and UTC timestamp for `ingested_at`; a test
      asserts the declared schema against a written file.
- [x] A test asserts there is no public method or code path that returns a `DailyBar` with modified
      OHLC values — adjusted prices are produced as separate derived values by QNT-015.

## Technical notes
`Decimal` is required by DEC-005: split and dividend arithmetic on floats accumulates error that
shows up as small, plausible, wrong returns. Choose a precision and scale that accommodates both
pence-quoted LSE prices and high-priced US securities, and pin it in the schema rather than letting
Parquet infer it (QNT-008 established this pattern).

Volume is an integer for equities but some providers report fractional or scaled volume for certain
venues; decide and document a single representation, rejecting rather than rounding values that do
not fit it.

The raw/adjusted distinction from `docs/QUANT_PRINCIPLES.md` §3 is structural here: this model holds
only as-traded values, and the field names must make that unmistakable. Where a provider supplies
its own adjusted close, retain it as a distinctly named cross-check field — useful for validating
our own adjustment factors in QNT-015 — but never let it flow into returns.

Zero-price rejection deserves care: a genuinely suspended security has no bar rather than a zero
bar, and providers that emit zeros are reporting missing data. Rejecting at the boundary and letting
QNT-019 report the count is the behaviour the no-silent-coercion rule requires.

## Dependencies
QNT-006 — supplies `security_id` and the domain package conventions this model follows.

## Risks
Over-strict invariants could reject legitimate but unusual bars (for example a bar where open equals
high equals low equals close on a thinly traded day, which is valid). Mitigated by testing that
degenerate-but-valid bars are accepted, and by routing genuinely questionable data to QNT-019's
warning report rather than to construction failure where the value is not impossible.

## Testing requirements
`tests/domain/test_daily_bar.py`. Each invariant gets an accepted and a rejected case; include the
degenerate flat bar as an accepted case and a `GBX`-quoted bar asserting no implicit conversion
occurs. A `timetravel`-marked test is not required for the model alone, but the fixtures created
here must be reusable by QNT-018's and QNT-019's time-travel suites.

## Documentation requirements
`docs/DATA_MODEL.md` `prices_daily` section updated with the concrete field list, types, and the
invariant list.

## Completion notes
2026-08-16. `src/trp/domain/prices.py` (`DailyBar`) + `src/trp/canonical/prices.py`
(`PRICES_DAILY_SCHEMA`, `bars_to_frame`/`frame_to_bars`). Invariants reject impossible
bars naming the violated rule and values; zero/negative prices rejected; degenerate flat
zero-volume bar accepted (tested). Volume decision: whole shares as Int64 — fractional
volume rejected, never rounded (documented in module docstring). Decimal pinned at
Parquet `Decimal(18,6)` (Polars-declared, consistent with the QNT-008 pattern rather than
a separate PyArrow schema object) — holds GBX quotes and six-figure USD prices exactly;
on-disk schema asserted against the declaration, Decimal round trip exact. Provider
adjusted close retained as `provider_adjusted_close` cross-check field only. GBX recorded
as quotation unit, no implicit conversion (tested). Tests:
`tests/domain/test_daily_bar.py`. All checks green (157 tests).
