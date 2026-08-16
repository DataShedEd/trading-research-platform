# QNT-010 — Ticker, listing and status change handling

- **Ticket ID:** QNT-010
- **Status:** DONE
- **Priority:** P1
- **Epic:** EPIC 2 — Security Master

## Problem
Corporate lifecycle events touch three tables at once. A ticker change closes an identifier row,
opens another, and may also change the listing; a delisting ends the listing, sets a status, and
must stop all subsequent activity. Applying these by hand invites inconsistent states — an
identifier still valid after its listing ended, or a price row dated after delisting — that no
single-table validator would catch.

## Objective
Helpers that apply a lifecycle event (rename, ticker change, exchange move, delisting, acquisition)
as a consistent set of new effective-dated rows across the security, status, listing, and identifier
tables, with cross-table invariants enforced.

## Scope
`src/trp/canonical/securities/events.py` providing a `SecurityEvent` model per event type and an
`apply_event(master, event) -> SecurityMaster` function returning a new, validated master state;
cross-table invariant checks; fixture-driven tests.

Events covered: entity rename, ticker change, exchange move (change of listing venue), delisting
(voluntary, failure, or regulatory), and acquisition (target ceases, with the acquirer recorded).

## Out of scope
Sourcing events from a provider feed (Epic 3 ingestion), price adjustment arithmetic (QNT-015),
knowledge-time modelling of when we learned of an event (QNT-011).

## Acceptance criteria
- [x] Each event type is a frozen Pydantic model carrying an effective date, a source, and the
      fields that event needs; `apply_event` is pure — it returns a new master, never mutates its
      input, and applying the same event twice is either rejected with a typed error or is a no-op
      per a documented, tested choice.
- [x] Applying a ticker change produces exactly one closed identifier row and one new open row with
      contiguous ranges, leaves `security_id` unchanged, and leaves the listing's other fields
      untouched.
- [x] Applying a delisting sets `valid_to` and the delisting date and reason on the listing, appends
      a `delisted` status row effective from that date, and closes every identifier row for the
      security on that date.
- [x] A cross-table invariant check rejects any master state with an identifier or listing valid
      after the security's delisting date, naming the offending rows.
- [x] Applying an exchange move closes the old listing and opens a new one with the new MIC and its
      currency, and creates a new `(TICKER, exchange)` identifier row for the new venue.
- [x] Applying an acquisition sets the target's status to `acquired` with the acquirer's
      `security_id` or `entity_id` recorded, and does not delete or alter any historical row.

## Technical notes
Every event is additive: rows are closed by setting `valid_to`, never deleted, and no historical row
is ever edited in place beyond that closure. This is the concrete expression of the survivorship-bias
rule in `docs/QUANT_PRINCIPLES.md` — a company that failed in 2009 must still be fully described in
2026.

Delisting reason matters for backtest accounting: a failure implies zero or near-zero proceeds,
whereas an acquisition implies cash or stock consideration. Model the reason as an enum, not free
text, so the backtester (Epic 6) can branch on it without string matching.

`apply_event` re-runs the QNT-007 overlap check and the new cross-table checks on the resulting
state, so an inconsistent master cannot be produced by a helper even if the event data is odd.
Prefer returning a rich error naming the rows over raising a bare assertion.

An acquisition where the acquirer is itself in the master should link the two by `security_id`; when
the acquirer is unknown or unlisted, record the name and leave the link null rather than inventing
an entity.

## Dependencies
QNT-009 — events are expressed against resolved securities and the helpers reuse its index and
typed errors; transitively QNT-007/QNT-008 for the invariants and store.

## Risks
An event applied with the wrong effective date corrupts a range boundary in a way that only shows up
as a subtly wrong backtest. Mitigated by the fixture-driven tests, and by QNT-019's data-quality
checks flagging prices that fall outside a listing's validity.

## Testing requirements
`tests/canonical/test_security_events.py` plus `tests/timetravel/test_event_timetravel.py` (marker
`timetravel`). Fixture-driven: one fixture per event type built from realistic dates, asserting the
exact set of rows before and after. The `timetravel` test asserts that a master with a 2015 event
applied answers queries about 2012 identically to a master without it.

## Documentation requirements
`docs/DATA_MODEL.md` gains a short subsection listing the event types and the rows each produces.
`docs/DECISIONS.md` entry if the duplicate-event behaviour (reject versus no-op) is contentious.

## Completion notes
2026-08-16. `src/trp/domain/changes.py`: frozen event models (`TickerChange`,
`EntityRename`, `ExchangeMove`, `Delisting`, `Acquisition`) with `apply_event` dispatch to
pure functions returning a new, fully revalidated master. Delisting reason is the
`DelistingReason` enum; `Delisting(reason=FAILURE)` maps to `LIQUIDATED` status, others to
`DELISTED`; acquisitions record `related_security_id` (None for unknown/unlisted acquirers).
Cross-table invariant (nothing in force past a terminal status date) added to the
`SecurityMaster` aggregate, so it holds everywhere, not just in these helpers. Duplicate
application is rejected with `ChangeError` (documented choice: reject, not no-op).
Events compose with the bitemporal knowledge axis: `knowledge_time` supersedes revised rows
(QNT-011/DEC-008). Deviation: entity rename updates the current label only (name history
deferred with QNT-006). Tests: `tests/domain/test_changes.py`, `test_events.py`; the
2015-event-doesn't-change-2012-answers property is covered by the knowledge-view tests in
`tests/timetravel/test_security_master_pit.py`.
