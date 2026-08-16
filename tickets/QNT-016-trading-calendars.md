# QNT-016 — Trading calendars

- **Ticket ID:** QNT-016
- **Status:** BACKLOG
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
- [ ] `TradingCalendar` is constructed for `XLON` and answers `is_trading_day` correctly for a known
      LSE holiday (for example a Christmas or Easter closure) and for a normal trading day either
      side of it.
- [ ] `previous_trading_day` and `next_trading_day` skip weekends and holidays, and a test covers a
      date falling immediately after a multi-day closure.
- [ ] `sessions_between` returns an inclusive-of-both-endpoints or documented half-open range of
      trading days, matching a hand-counted expected count for a chosen month.
- [ ] Half days (for example an LSE Christmas Eve early close) are identifiable via `is_half_day`
      and are still trading days.
- [ ] Querying a date outside the calendar's supported range raises a typed error rather than
      returning a plausible-looking answer derived from weekday logic.
- [ ] A `DECISIONS.md` entry records the implementation choice (library versus curated data), its
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
_Not started._
