# QNT-009 — Identifier resolution service

- **Ticket ID:** QNT-009
- **Status:** DONE
- **Priority:** P1
- **Epic:** EPIC 2 — Security Master

## Problem
Provider payloads, universe files, and research notebooks all arrive holding external identifiers.
Turning those into an internal `security_id` is the single most dangerous operation in the platform:
resolving without a date, or guessing when a value is ambiguous, attaches history to the wrong
company and produces backtest results that look plausible and are wrong.

## Objective
A resolution service that maps `(value, kind, on_date)` to exactly one `security_id`, plus the
reverse lookup returning the identifiers valid for a security on a date, raising typed errors on
ambiguity or absence rather than returning a best guess.

## Scope
`src/trp/canonical/securities/resolution.py` providing:

- `resolve(value, kind, on_date, *, exchange=None) -> SecurityId`
- `resolve_many(...)` for bulk resolution over a dataframe column
- `identifiers_for(security_id, on_date) -> Sequence[IdentifierMap]`
- typed exceptions `IdentifierNotFound` and `AmbiguousIdentifier`

Also in scope: an in-memory index built from the QNT-008 store, and the value-normalisation path
shared with QNT-007 so that lookups match regardless of case or whitespace.

## Out of scope
Knowledge-time (`as_of`) filtering — that is QNT-011 and layers on top of this. Lifecycle-event
application (QNT-010). Fuzzy or name-based matching of any kind.

## Acceptance criteria
- [x] `resolve` requires `on_date` as a positional-or-keyword argument with no default; a call
      without it is a type error under `mypy --strict`.
- [x] Resolving a ticker that belonged to company A until 2015 and to company B afterwards returns
      A's `security_id` for a 2013 date and B's for a 2019 date.
- [x] A value with no valid mapping on `on_date` raises `IdentifierNotFound` carrying the value,
      kind, and date; it never returns `None` and never falls back to the nearest date.
- [x] `AmbiguousIdentifier` is raised, listing every candidate `security_id` and applying no
      tie-break heuristic, both when two securities are validly mapped to the same
      `(value, kind, exchange)` on the same date and when `kind=TICKER` is resolved without an
      `exchange` while the ticker is valid on more than one venue.
- [x] `identifiers_for` returns only records whose validity range contains `on_date`, and a test
      asserts an identifier retired before the date is absent.
- [x] `resolve_many` over a Polars column returns resolutions in input order and reports failures as
      structured rows rather than raising on the first bad value, with a documented strict mode that
      does raise.

## Technical notes
Resolution reads the `identifier_map` table written by QNT-008 and applies the half-open range
convention from QNT-006. Build the index once per service instance keyed by
`(kind, exchange, normalised_value)` to a list of `(valid_from, valid_to, security_id)` intervals,
then binary-search within the list — the master is small enough that a sorted-list interval search
is ample and keeps behaviour obvious.

The "never guess" rule is the point of this ticket. Any temptation to prefer the primary listing,
the most recent record, or the record from the preferred provider must be resisted: those
heuristics are individually reasonable and collectively produce untraceable misattribution. If a
caller genuinely wants a preference order, it belongs in the caller, stated explicitly.

`resolve_many` exists because bulk ingestion resolves tens of thousands of values and per-row
exception handling is both slow and hostile to diagnosis; returning a failure frame lets the caller
report every unresolvable identifier at once.

## Dependencies
QNT-008 — supplies the persisted `identifier_map` and the reader this service indexes.

## Risks
Callers may be tempted to catch `IdentifierNotFound` and skip the row, quietly shrinking the
universe and reintroducing survivorship bias. Mitigated by making `resolve_many` surface failures as
data that a caller must consciously handle, and by covering the failure path in QNT-019's validation
report.

## Testing requirements
`tests/canonical/test_resolution.py` plus `tests/timetravel/test_resolution_timetravel.py` (pytest
marker `timetravel`). Required cases: an old ticker resolving to the correct security on a
historical date; the same ticker resolving to a different security after reassignment; ambiguity
raising rather than picking; a missing mapping raising; reverse lookup excluding retired
identifiers. The `timetravel` test asserts that resolution on a historical date cannot return a
security whose mapping only began later.

## Documentation requirements
`docs/DATA_MODEL.md` resolution paragraph updated with the function signatures and the typed-error
contract; a short usage example in the module docstring showing why `on_date` is mandatory.

## Completion notes
2026-08-16. `src/trp/domain/resolution.py` (domain service over an in-memory
`SecurityMaster`, rather than reading the store directly — the store round-trips the same
models, QNT-008). `IdentifierResolver.resolve(value, kind, on, *, mic, provider)` with typed
`UnknownIdentifier` / `AmbiguousIdentifier` (candidates listed, no tie-break, no
nearest-date fallback); `identifiers_for` reverse lookup excludes retired records;
`resolve_many` returns a Polars frame (`value`, `security_id`, `error`) preserving input
order, failures as rows, with `strict=True` raising. Superseded records are excluded —
knowledge-time resolution goes through `PointInTimeSecurityMaster` (QNT-011). Deviations:
`on` is positional-or-keyword without default (mypy-enforced presence); dict-index +
linear scan within group instead of binary search — the master is small and behaviour
obvious; revisit only with evidence. Timetravel-relevant resolution cases live in
`tests/timetravel/test_security_master_pit.py` rather than a separate file. Tests:
`tests/domain/test_resolution.py` (ticker reassignment across dates, gap → unknown,
cross-exchange ambiguity, bulk resolution).
