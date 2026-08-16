# QNT-006 — Security master domain model

- **Ticket ID:** QNT-006
- **Status:** DONE
- **Priority:** P1
- **Epic:** EPIC 2 — Security Master

## Problem
Every other dataset in the platform hangs off a security identifier. Without an immutable internal
identifier and effective-dated lifecycle records, the system inherits the provider's habit of
treating a ticker as a permanent key, which silently destroys delisted and renamed companies and
reintroduces survivorship bias.

## Objective
Define the security master domain records in `trp.domain` as Pydantic v2 frozen models — `Entity`,
`Security`, `Listing`, and effective-dated security status — with the enumerations and validation
invariants that make an invalid record unconstructable.

## Scope
`src/trp/domain/` package (`entity.py`, `security.py`, `listing.py`, `enums.py`, `__init__.py`
re-exporting the public names); enums for security type, security status, and identifier kind;
field validators and model validators enforcing the invariants below; unit tests.

Model fields follow `docs/DATA_MODEL.md`:

- `Entity` — `entity_id`, name, country of incorporation, name-history support.
- `Security` — `security_id`, `entity_id`, security type, primary currency where known.
- `SecurityStatus` — `security_id`, status, `effective_from`, `effective_to` (open-ended when
  current), reason, source.
- `Listing` — `security_id`, exchange MIC, listed ticker, currency, `valid_from`, `valid_to`,
  delisting date and delisting reason where known.

## Out of scope
Identifier mapping records (QNT-007), persistence (QNT-008), resolution (QNT-009), lifecycle-event
application helpers (QNT-010), point-in-time query API (QNT-011).

## Acceptance criteria
- [x] `trp.domain` exports frozen (`model_config = ConfigDict(frozen=True)`) Pydantic v2 models
      `Entity`, `Security`, `SecurityStatus`, `Listing`, and the enums `SecurityType`,
      `SecurityStatus`-value enum, and `IdentifierKind`; `mypy --strict` passes.
- [x] Constructing a record whose `valid_to`/`effective_to` is earlier than its
      `valid_from`/`effective_from` raises `ValidationError`; equal dates are rejected unless the
      range is explicitly documented as inclusive-of-a-single-day.
- [x] Exchange MIC is validated as a four-character uppercase ISO 10383 code and currency as a
      three-character uppercase ISO 4217 code (`GBX` permitted as a documented quotation unit).
- [x] A `Listing` with a delisting date must have `valid_to` equal to that date, and a `Listing`
      carrying a delisting reason must carry a delisting date.
- [x] `security_id` and `entity_id` are opaque string identifiers validated against a documented
      format; there is no code path that derives one from a ticker.
- [x] Unit tests cover each invariant with both an accepted and a rejected example, and assert that
      mutation of a constructed model raises.

## Technical notes
Per DEC-005 these are Pydantic v2 frozen models; timestamps are timezone-aware UTC and market-local
concepts (`valid_from`, `valid_to`, delisting date) are `datetime.date`. Money-typed fields use
`Decimal`, never `float`.

`security_id` is internal, immutable, and **never reused** — document this in the model docstring
and make identifier generation a separate explicit function rather than a default factory, so that
reconstruction from storage never mints a new one. Deciding the identifier format (opaque ULID-like
string versus a readable composite) is part of this ticket; record the choice in a `DECISIONS.md`
entry if it constrains later work.

Represent open-ended validity as `valid_to = None` rather than a sentinel far-future date, so that
"currently valid" is a type-level distinction rather than a magic value. Half-open ranges
(`valid_from` inclusive, `valid_to` exclusive) are recommended; whichever convention is chosen must
be stated in the docstrings and used consistently by QNT-007 onwards, since overlap detection
depends on it.

Status is effective-dated rather than a single mutable field: a security that delists in 2011 and
is later acquired has two status rows, and a query as at 2010 must see neither.

## Dependencies
QNT-003 — settings and logging that the domain package's tests and future loaders rely on.

## Risks
Getting the range convention or the identifier-immutability rule wrong here propagates into every
downstream table and is expensive to correct after data has been written. Mitigated by fixing the
convention explicitly in docstrings and asserting it in tests before QNT-007 begins.

## Testing requirements
`tests/domain/test_security_model.py`, `tests/domain/test_listing_model.py`. Property-style tests
for date-range validation; explicit rejection tests for mutation attempts, invalid MIC, invalid
currency, and inverted ranges. No time-travel test required — this ticket adds no data-access API —
but the fixtures created here should be reusable by the `timetravel` suites in QNT-011 and QNT-012.

## Documentation requirements
`docs/DATA_MODEL.md` security master section updated to point at `trp.domain` as the authoritative
definition and to state the chosen range convention. A `DECISIONS.md` entry if the `security_id`
format decision is non-obvious.

## Completion notes
2026-08-16. Implemented in `src/trp/domain/{identifiers,security,ranges}.py` with re-exports
from `trp.domain`; single `security.py` module rather than the sketched entity/listing split.
Records: `Entity`, `Security`, `SecurityStatusPeriod` (status history), `Listing`; enums
`SecurityType`, `SecurityStatus`, `DelistingReason`, `IdentifierKind`. Half-open ranges
`[valid_from, valid_to)`, `valid_to=None` open-ended, via `EffectiveDated` mixin — which also
carries the bitemporal knowledge axis (`recorded_at`/`superseded_at`, DEC-008, added by
QNT-011). IDs are `SEC-`/`ENT-` + UUID4, minted only by explicit `new_*_id()` functions.
Deviations: `Security` has no primary-currency field (quote currency lives on `Listing`);
entity name history deferred (documented in the docstring); no Decimal fields exist in these
tables yet. Tests: `tests/domain/test_security.py`, `test_ranges.py`. All checks green.
