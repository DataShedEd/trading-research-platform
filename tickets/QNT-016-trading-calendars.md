# QNT-016 — Trading calendars

- **Ticket ID:** QNT-016
- **Status:** DONE
- **Priority:** P1
- **Epic:** EPIC 3 — Market Data

## Problem
Without a per-exchange trading calendar there is no way to tell a genuine data gap from a market
holiday, no correct definition of "the previous trading day" for return and adjustment
calculations, and no correct rebalance date arithmetic. Assuming weekdays are trading days is wrong
for every market and badly wrong for the LSE.

## Objective
Per-exchange trading calendars — LSE first, NYSE and Nasdaq next — exposing trading days, holidays
and half days, with helpers for next/previous trading day and sessions between dates, and a recorded
decision on the implementation approach.

## Scope
`src/trp/canonical/calendars.py` providing:

- `TradingCalendar` for an exchange MIC with `is_trading_day(date)`, `next_trading_day(date)`,
  `previous_trading_day(date)`, `sessions_between(start, end)`, `is_half_day(date)`
- a registry mapping MIC to calendar, covering `XLON` initially and `XNYS`/`XNAS` next
- the chosen data source, whether the `exchange-calendars` library or curated data files

## Out of scope
Intraday session times and market microstructure, settlement calendars, FX and bond market
calendars, holiday calendars for exchanges beyond the three named.

## Acceptance criteria
- [x] `TradingCalendar` is constructed for `XLON` and answers `is_trading_day` correctly for a known
      LSE holiday (for example a Christmas or Easter closure) and for a normal trading day either
      side of it.
- [x] `previous_trading_day` and `next_trading_day` skip weekends and holidays, and a test covers a
      date falling immediately after a multi-day closure.
- [x] `sessions_between` returns an inclusive-of-both-endpoints or documented half-open range of
      trading days, matching a hand-counted expected count for a chosen month.
- [x] Half days (for example an LSE Christmas Eve early close) are identifiable via `is_half_day`
      and are still trading days.
- [x] Querying a date outside the calendar's supported range raises a typed error rather than
      returning a plausible-looking answer derived from weekday logic.
- [x] A `DECISIONS.md` entry records the implementation choice (library versus curated data), its
      alternatives, and its consequences for offline reproducibility.

## Technical notes
The implementation choice is a real decision, not a formality. `exchange-calendars` is well
maintained and covers the venues needed, but it is a moving dependency whose historical holiday data
can change between versions — which would silently change past backtest results and violate the
reproducibility rule in `docs/QUANT_PRINCIPLES.md` §4. Curated data files are more work and are
stable and auditable. A reasonable resolution is to use the library but snapshot its output to
committed data files, pinning the version and treating the snapshot as canonical; whichever is
chosen, record it and its consequences.

Calendars are dates, not timestamps, per the DEC-005 convention: a trading day is a market-local
date. Do not model session open and close times in this ticket even if the chosen source provides
them, and do not let a UTC conversion silently shift a session across a date boundary.

Cache calendars per exchange at module level with an explicit accessor rather than reconstructing
them per call — `previous_trading_day` is called once per security per bar in the adjustment engine
and per-call construction dominates the runtime.

Half days matter mainly for volume anomaly detection in QNT-019: half-day volume is legitimately a
fraction of normal and must not be reported as an anomaly.

## Dependencies
QNT-003 — settings supply the data-layer paths where a calendar snapshot would be written.

## Risks
Historical LSE holiday data before roughly 2000 is patchy in most sources, so early history may
have incorrect trading days. Mitigated by bounding the calendar's supported range explicitly and
raising outside it, and by reconciling calendar days against observed price dates in QNT-019 so
disagreements surface as evidence rather than assumption.

## Testing requirements
`tests/canonical/test_calendars.py`. Required cases: a known LSE holiday, a known LSE half day, a
multi-day closure traversal, a hand-counted `sessions_between` result, and an out-of-range query
raising. Also a missing-trading-day scenario: a security with no bar on a valid trading day is
detectable as a gap (the check itself lives in QNT-019, but the calendar side is asserted here). A
`timetravel` marker is not required as calendars carry no knowledge-time axis, but if the snapshot
approach is chosen, a test must assert the snapshot is used rather than a live library call.

## Documentation requirements
`docs/DECISIONS.md` entry (mandatory, per the acceptance criteria). `docs/DATA_MODEL.md`
`trading_calendars` section updated with the chosen source and the supported date range per
exchange.

## Completion notes
2026-08-16 — `src/trp/canonical/calendars.py`: `TradingCalendar` with `is_trading_day`,
`is_half_day`, `next_trading_day`, `previous_trading_day`, `sessions_between` (inclusive of both
endpoints, documented on the method) and `missing_sessions` — the calendar half of the QNT-019 gap
check, which returns trading days in a range with no observed bar. `get_trading_calendar(mic)` is
the explicit accessor over a module-level per-MIC cache; MIC → library calendar code is an explicit
map covering `XLON`, `XNYS`, `XNAS`, and an unknown MIC raises `UnknownExchange`.

Source: the `exchange-calendars` library, recorded as DEC-010 with its alternatives and its
reproducibility consequences. Snapshotting the library output to committed files (the technical
note's suggested middle path) was **not** done — deviation from the note, deliberate and recorded
in DEC-010: a snapshot taken before QNT-019 reconciles calendar days against observed price dates
would freeze unverified data. The reproducibility risk is bounded instead by the version pin in
`uv.lock`, by tests asserting hand-derived expected values rather than the library's own output
(so a changed historical calendar fails tests instead of silently changing backtests), and by a
supported range fixed in code. Curated overrides or a snapshot can be layered on the wrapper later
without changing any caller.

Sessions for the supported range are materialised once per exchange at construction and all queries
are bisect lookups over that sorted tuple, so nothing reconstructs a calendar per call. The
supported range is fixed at 2000-01-01 to 2030-12-31 rather than the library's default, which is
anchored to today and would make the same historical query answerable one year and out of range the
next; outside it every method raises `DateOutOfCalendarRange`. `next_trading_day` /
`previous_trading_day` raise `CalendarRangeExhausted` when the answer exists but falls outside the
supported range, rather than returning a value the calendar does not vouch for. Half days are
derived as sessions shorter than the exchange's modal session length — session *length* rather than
close time, because it is invariant under daylight saving and needs no timezone conversion; only
dates cross the module boundary, so no UTC conversion can shift a session across a date boundary.

Tests: `tests/canonical/test_calendars.py`, 32 tests, all passing. Cover the 2012 Diamond Jubilee
four-day LSE closure, Christmas/Boxing Day and Easter closures, ordinary weekends, LSE Christmas
Eve and New Year's Eve half days plus the NYSE day-after-Thanksgiving early close, multi-day
closure traversal in both directions, hand-counted `sessions_between` for June 2012 (19 sessions)
and a chosen week, out-of-range queries on every method, unknown MIC, and the missing-trading-day
scenario (a security missing one mid-week bar is reported; a market holiday is not).
`docs/DATA_MODEL.md` `trading_calendars` section updated with the source and supported ranges.

Not done, as scoped out or deferred: no `timetravel` marker (calendars carry no knowledge-time
axis, per the testing requirements); no snapshot-usage test, since no snapshot was taken; no
session times, settlement, FX or bond calendars. QNT-003 settings paths were not needed because
nothing is written to the data layer.
