# QNT-007 — Identifier mapping with effective date ranges

- **Ticket ID:** QNT-007
- **Status:** DONE
- **Priority:** P1
- **Epic:** EPIC 2 — Security Master

## Problem
External identifiers are not stable. Tickers are reassigned, SEDOLs change on corporate events, and
providers use their own keys. If an identifier is stored as a single mutable field, a historical
query resolves a 2008 ticker to whichever company holds it today — a silent, invisible source of
look-ahead and misattribution.

## Objective
Model external identifiers as effective-dated `IdentifierMap` records keyed by `security_id`, with
an enforced invariant that no two records for the same `(security_id, kind)` have overlapping
validity, and with ticker changes represented as two rows rather than an update.

## Scope
`src/trp/domain/identifier.py` defining `IdentifierMap`; a validity-overlap checker operating over
a collection of records; normalisation rules per identifier kind; unit tests.

`IdentifierMap` fields per `docs/DATA_MODEL.md`: `security_id`, `kind` (`ISIN` | `SEDOL` | `CUSIP` |
`TICKER` | provider-specific), `value`, `exchange` MIC (required for `TICKER`, absent otherwise),
`valid_from`, `valid_to`, `source`.

## Out of scope
Persistence (QNT-008), the resolution service and its error types (QNT-009), applying corporate
lifecycle events (QNT-010), knowledge-time filtering (QNT-011).

## Acceptance criteria
- [x] `IdentifierMap` is a frozen Pydantic v2 model; `kind` uses the `IdentifierKind` enum from
      QNT-006; `exchange` is required when `kind` is `TICKER` and rejected otherwise.
- [x] Identifier values are normalised on construction — uppercased, whitespace stripped — and
      ISIN check-digit validation rejects a malformed ISIN with a typed validation error.
- [x] A function such as `check_no_overlaps(records)` raises a typed error naming both offending
      records when two records share `(security_id, kind, exchange)` and their validity ranges
      overlap; adjacent ranges that merely touch are accepted.
- [x] The same identifier value may map to different securities in disjoint periods (ticker reuse)
      and this is accepted; the same value mapping to two securities in overlapping periods is
      rejected by a documented check.
- [x] A ticker change is expressible only as closing the old row (`valid_to` set) and inserting a
      new row; a test asserts there is no supported code path that mutates an existing row's value.
- [x] Unit tests cover overlap detection (identical, contained, straddling, touching, disjoint) and
      a worked ticker-change fixture producing exactly two rows with contiguous ranges.

## Technical notes
Follow the half-open range convention fixed in QNT-006 (`valid_from` inclusive, `valid_to`
exclusive, `None` meaning open-ended); overlap logic must handle the open-ended case explicitly
rather than substituting a far-future date.

Overlap checking is O(n log n) by sorting per `(security_id, kind, exchange)` group and comparing
consecutive ranges. Keep it a pure function over an iterable of records so it can be reused by the
storage writer (QNT-008) as a pre-write validation and by the lifecycle helpers (QNT-010).

Ticker reuse is a genuine occurrence — the invariant is uniqueness of the mapping *within a period*,
not global uniqueness of the value. This distinction is the reason resolution (QNT-009) must always
take a date.

Provider-specific identifiers carry the provider name in `source`; two providers may supply
conflicting mappings for the same security, so `source` participates in provenance but not in the
overlap key. Conflicting cross-source mappings surface as an ambiguity error at resolution time
rather than being silently deduplicated here.

## Dependencies
QNT-006 — supplies `security_id`, the `IdentifierKind` enum, and the date-range convention.

## Risks
Over-strict validation (for example rejecting SEDOLs that fail a check digit for legitimately old
records) could drop real history. Mitigated by validating format strictly only where the standard is
unambiguous (ISIN) and recording, not rejecting, questionable values elsewhere.

## Testing requirements
`tests/domain/test_identifier_map.py`, `tests/domain/test_overlap_detection.py`. Include a fixture
representing a real-shaped ticker change (old ticker closed on the effective date, new ticker opened
the same day) and assert both that resolution inputs remain unambiguous and that no gap exists
between the rows.

## Documentation requirements
`docs/DATA_MODEL.md` `identifier_map` section updated with the normalisation rules and the
overlap invariant.

## Completion notes
2026-08-16. Implemented as `IdentifierRecord` (name differs from the sketched
`IdentifierMap`) in `src/trp/domain/identifier_map.py`, with check-digit validation for ISIN,
SEDOL **and** CUSIP in `identifier_validation.py` (stricter than the ticket's ISIN-only
minimum). `find_mapping_conflicts` returns `MappingConflict` objects naming both records;
the `SecurityMaster` aggregate (QNT-008) raises on them at construction. Overlap detection is
O(n log n) via `ranges.first_overlap`. Deviations: values are rejected rather than
case-normalised (no silent coercion — DEC-005 spirit); `mic` is permitted on non-ticker kinds
(SEDOLs are market-scoped). Known tension, per this ticket's Risks: if the bake-off surfaces
genuine old SEDOLs failing the checksum, ingest them as `PROVIDER`-kind identifiers rather
than weakening the validator. Tests: `test_identifier_validation.py`, `test_identifier_map.py`
(ticker change as two rows, recycling legal, overlap conflicts).
