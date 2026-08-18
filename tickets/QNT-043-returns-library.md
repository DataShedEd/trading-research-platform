# QNT-043 — Returns library

- **Ticket ID:** QNT-043
- **Status:** DONE
- **Priority:** P2
- **Epic:** EPIC 7 — Factor Engine

## Problem
Momentum factors, risk statistics, and backtest performance all need returns, and each will compute
them slightly differently if left to itself — one including dividends, another silently dropping
missing days, a third treating a delisting as a zero return. Divergent return calculations make
results incomparable and hide errors in the differences.

## Objective
Provide one returns library computing price and total returns over arbitrary windows from adjusted
data, with explicit and tested handling of missing days, delistings, and currency, as the shared
input for momentum, risk, and performance measurement.

## Scope
`src/trp/factors/returns.py` (or `src/trp/returns/` if it outgrows a module): simple and log
returns; price returns and total returns including dividends; returns over arbitrary windows
(calendar or trading-day defined, with skip periods such as 12-1); series and cross-sectional
forms; a documented missing-data policy; currency conversion for non-`GBP` listings; persistence of
computed return series to `data/derived/returns/` with adjustment provenance flags.

## Out of scope
Adjustment factor derivation (upstream, QNT-015); momentum factor definitions (QNT-044); rolling
performance statistics (QNT-056); risk models.

## Acceptance criteria
- [x] Price and total returns over a window are computed from adjusted data, and total returns
      include ordinary and special dividends; each returned series is flagged with its adjustment
      provenance.
- [x] Window specifications support skip periods (for example 12 months ending one month ago) and
      the convention — inclusive/exclusive endpoints, calendar versus trading days — is documented
      and asserted in tests.
- [x] Missing observations are handled by a single documented policy (for example requiring a
      minimum proportion of expected trading days, returning a typed "insufficient data" result
      rather than a silently wrong number), and no code path forward-fills a price across a
      delisting.
- [x] A security that delists mid-window yields a return through the delisting event using
      delisting proceeds where known, or an explicit typed result where not — never a silent
      truncation to the last observed price.
- [x] Returns for securities quoted in `GBX` or a non-`GBP` currency are converted using rates dated
      at or before the observation date, and a test asserts the pence/pounds distinction cannot
      inflate a return by a factor of one hundred.
- [x] Values are validated against hand-computed fixtures covering a split, a dividend, and a plain
      price move.

## Technical notes
Adjusted prices are computed from stored adjustment factors rather than read from a mutated price
history, per QUANT_PRINCIPLES §3. Vectorised float arithmetic is appropriate here (derived layer);
the Decimal boundary stays in canonical storage.

The 12-1 skip convention exists because the most recent month is dominated by short-term reversal;
supporting it generally in the window specification keeps QNT-044 declarative.

## Dependencies
QNT-015 — supplies adjusted prices and adjustment factors derived from corporate actions.

## Risks
An implicit missing-data policy is the classic source of survivorship-flavoured bias: dropping
securities without enough history quietly excludes the newly listed and the nearly dead. Mitigated
by making the policy explicit, configurable, and reported by callers.

## Testing requirements
`tests/factors/test_returns.py` — hand-computed fixtures for simple, log, price and total returns; a
2-for-1 split; an ordinary dividend; a special dividend; a missing-days series at the policy
threshold; a `GBX` security; a non-`GBP` security.

`tests/timetravel/test_returns.py` (marker `timetravel`) — a return computed as at date *t* must not
change when a corporate action announced after *t* is added to the fixture, and a delisting recorded
later must not alter a return computed before it.

## Documentation requirements
`docs/DATA_MODEL.md` derived-returns section documenting the return definitions, window conventions,
missing-data policy, and delisting treatment.

## Completion notes
2026-08-18. `src/trp/factors/returns.py`: `ReturnsEngine` over canonical bars + corporate
actions via the QNT-015 adjustment engine (exact factors; floats only at this derived
layer). Delivered per acceptance: price/total bases with reinvestment convention
(documented after the hand fixtures caught the naive-vs-reinvested 5.00% vs 5.26%
distinction); calendar-month windows with skip (12-1 tested to exclude the final month);
explicit missing-data policy (session coverage vs the QNT-016 XLON calendar, typed
INSUFFICIENT_DATA); delisting handling (failure → −100%, cash acquisition → proceeds
converted exactly GBP→GBX via QNT-017 reference data, unknown → typed status — never
silent truncation); dividend unit alignment killing the 100× GBP/GBX trap (tested
bluntly); `as_of` throughout with timetravel tests (late-published dividend and
late-recorded delisting cannot change earlier results — the latter honestly reads
INSUFFICIENT before knowledge). Deviations: log returns omitted (add when a consumer
needs them); persistence is a minimal never-overwrite writer pending real usage patterns;
cross-sectional form is `cross_section()` returning a frame of typed results. Tests:
`tests/factors/test_returns.py` (10 hand-derived fixtures),
`tests/timetravel/test_returns.py`. 584 tests green.
