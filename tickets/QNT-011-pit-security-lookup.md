# QNT-011 — Point-in-time security lookup API

- **Ticket ID:** QNT-011
- **Status:** BACKLOG
- **Priority:** P1
- **Epic:** EPIC 2 — Security Master

## Problem
QNT-009 answers "what was true on this date" using the master as it stands today. That is not the
same question as "what did we know on this date". If a provider backfills a 2014 ticker change in
2026, a backtest run over 2014 will silently use a mapping nobody had at the time. Event time and
knowledge time are different axes and conflating them is a look-ahead bug that no single-date query
can detect.

## Objective
A point-in-time lookup API over the security master that takes an explicit `as_of` knowledge
timestamp alongside the event date, and never returns a row whose `available_at` is later than
`as_of`.

## Scope
`src/trp/canonical/securities/pit.py` providing a `PointInTimeSecurityMaster` with:

- `resolve(value, kind, on_date, *, as_of, exchange=None)`
- `identifiers_for(security_id, on_date, *, as_of)`
- `listing_for(security_id, on_date, *, as_of)`
- `status_at(security_id, on_date, *, as_of)`

plus an `available_at` field added to the identifier, listing, and status records, and the
conservative imputation path for sources that do not supply one.

## Out of scope
Fundamentals point-in-time handling (Epic 4), price data as-of queries (Epic 3), any change to the
resolution semantics themselves — this ticket wraps QNT-009 rather than replacing it.

## Acceptance criteria
- [ ] Every public method requires `as_of` as a keyword-only argument with no default; omitting it
      fails `mypy --strict`.
- [ ] Rows with `available_at > as_of` are excluded from every result; a test constructs a master
      where a ticker change was recorded late and asserts the old mapping is returned for an
      `as_of` before the record's `available_at`.
- [ ] Event date and knowledge date are independently variable: a matrix test over
      (`on_date`, `as_of`) pairs produces the documented expected result for each cell.
- [ ] Where a source supplies no `available_at`, it is imputed conservatively (late) per DEC-007 and
      the row carries an `available_at_imputed` flag that is visible in results.
- [ ] Passing an `as_of` earlier than the earliest known record returns an empty result or raises
      `IdentifierNotFound`, per the documented contract — never a silently unfiltered answer.
- [ ] `as_of` is validated as a timezone-aware UTC timestamp; a naive datetime is rejected.

## Technical notes
The two axes: `on_date` (a `datetime.date`, market-local, "when was this true") and `as_of` (a
timezone-aware UTC timestamp, "when did we know it"), consistent with DEC-005 and the conventions in
`docs/ARCHITECTURE.md`. Keeping their types different makes them hard to swap by accident, which is
deliberate.

Not every source distinguishes the axes. Where a provider gives only the effective date of a change,
impute `available_at` conservatively per DEC-007 — the effective date plus a documented lag, or the
ingestion timestamp where that is later — and flag it. A late-biased assumption can only make a
strategy look worse, which is the required direction of error under
`docs/QUANT_PRINCIPLES.md`.

Implement filtering as a predicate applied before the interval search rather than after, so that
ambiguity detection operates on the knowledge-filtered set: a mapping we did not yet know about must
not cause a spurious `AmbiguousIdentifier`.

This class is the interface the universe engine, factor engine, and backtester should use; QNT-009's
unfiltered API remains available for data-management tasks such as building the master itself, and
its docstring should say so plainly.

## Dependencies
QNT-009 — supplies resolution semantics, the index, and the typed errors this API filters and
re-raises.

## Risks
Cost of an extra filter on a hot path in bulk backtests; mitigated by pre-filtering the index once
per `as_of` when a backtest holds `as_of` constant, and by measuring before optimising. The larger
risk is a caller reaching past this API to QNT-009 for convenience — mitigated by documentation and
by the QNT-012 regression suite exercising the PIT path.

## Testing requirements
`tests/timetravel/test_pit_security_master.py` (pytest marker `timetravel`) is mandatory and is the
primary deliverable's proof: it must fail if knowledge-time filtering is removed. Cases: a
late-recorded ticker change invisible before its `available_at`; a security added to the master in
2020 invisible to an `as_of` in 2018; an imputed `available_at` producing the conservative (later)
visibility. Plus `tests/canonical/test_pit_api.py` for signature, validation, and error behaviour.

## Documentation requirements
`docs/DATA_MODEL.md` updated to state that security master rows carry `available_at` and that
`as_of` filters on it. `docs/QUANT_PRINCIPLES.md` point-in-time section cross-referenced from the
module docstring.

## Completion notes
_Not started._
