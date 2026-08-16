# QNT-073 — Securities, prices and fundamentals endpoints

- **Ticket ID:** QNT-073
- **Status:** BACKLOG
- **Priority:** P3
- **Epic:** EPIC 12 — Research API

## Problem
An HTTP layer is the easiest place to lose point-in-time correctness. A convenient
`GET /fundamentals/{id}` with no `as_of` parameter will return today's restated view, a caller will
use it to build a historical chart, and nothing in the response will indicate that the data could not
have been known at the time. The correctness guarantees enforced in the data layer have to be
enforced again at the boundary, because the boundary is where callers take shortcuts.

## Objective
Expose read-only endpoints over the security master, prices and fundamentals, with `as_of` required
on every historical read and adjusted versus as-traded prices explicitly distinguished.

## Scope
`trp.api` routers for: security search and lookup by internal id and by ticker (with effective-date
resolution), price series with an explicit adjustment mode, corporate actions for a security, and
fundamentals `as_of` a date. Pydantic response models, pagination, and query-parameter validation.

## Out of scope
Factors, universes, backtests and experiments (QNT-074); risk and signals (QNT-075); caching;
bulk export endpoints.

## Acceptance criteria
- [ ] Every endpoint returning historical data requires an explicit `as_of` query parameter; a
      request omitting it returns 422 rather than defaulting to today, asserted per endpoint.
- [ ] Price responses state their adjustment mode (as-traded or adjusted) and the adjustment basis
      used; requesting a series without specifying the mode is rejected.
- [ ] Ticker lookup resolves through effective-date ranges for the supplied `as_of` date and returns
      the immutable `security_id`; a ticker reused by a different company resolves correctly on both
      sides of the change.
- [ ] Fundamentals responses never include records with `available_at` greater than the requested
      `as_of`, covered by a `timetravel`-marked test through the HTTP layer.
- [ ] Delisted securities are returned by search and lookup with their delisting date rather than
      being absent.

## Technical notes
The endpoints are thin wrappers over the canonical query APIs and must not reimplement filtering — in
particular the `available_at` filter belongs in the data layer and is only passed through here. The
time-travel test at the HTTP layer exists to catch a router that forgot to forward `as_of`, not to
re-test the data layer.

Pagination on price series should be by date range rather than offset; a caller asking for twenty
years of daily data for the whole universe should be refused with a clear message pointing at the
Parquet layer.

## Dependencies
QNT-072 — the application skeleton these routers mount on; QNT-025 — the point-in-time fundamentals
query API they expose.

## Risks
A convenience default for `as_of` would silently reintroduce look-ahead for every consumer at once;
mitigated by the per-endpoint 422 assertion, which makes adding such a default a test failure.

## Testing requirements
`tests/api/test_data_endpoints.py` plus `tests/timetravel/test_api_asof.py` with the `timetravel`
marker: missing-`as_of` rejection per endpoint, ticker reuse resolution, adjustment-mode reporting,
and delisted-security visibility.

## Documentation requirements
OpenAPI descriptions state the `as_of` requirement and the adjustment-mode semantics on every
affected endpoint; `docs/ARCHITECTURE.md` notes that the API adds no query semantics of its own.

## Completion notes
_Not started._
