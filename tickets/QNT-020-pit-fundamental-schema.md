# QNT-020 — Point-in-time fundamental schema

- **Ticket ID:** QNT-020
- **Status:** BACKLOG
- **Priority:** P1
- **Epic:** EPIC 4 — Fundamental Data

## Problem
Fundamental data is the single easiest place in the platform to leak future information. A
provider's fundamentals endpoint typically returns the *current* view of a company's history:
restated figures presented as though they had always been known, with no publication timestamp at
all. Loading that shape into the canonical layer makes every value-factor backtest silently
look-ahead biased, and no amount of care further downstream can recover the lost information.
Before anything is ingested we need a record type that cannot represent a fundamental value
without also representing when it first became knowable.

## Objective
Define the `FundamentalValue` domain record in `trp.domain` as a Pydantic v2 frozen model carrying
the full point-in-time field set from `docs/DATA_MODEL.md`, with validation invariants that make an
unusable or ambiguous record unconstructable.

## Scope
`src/trp/domain/fundamentals.py` plus the enums it needs (added to `src/trp/domain/enums.py`) and
public re-exports from `src/trp/domain/__init__.py`; unit tests.

Fields, following `docs/DATA_MODEL.md`:

- `security_id` and/or `entity_id` — the subject of the statement (at least one required; the
  ticket decides and documents which is authoritative when both are present).
- `statement` — `StatementType` enum: income | balance | cash flow.
- `line_item` — the normalised canonical line-item name (taxonomy itself is QNT-021; this ticket
  types the field and requires it to be non-empty).
- `period_end` — `date`, the market-local period end.
- `period_type` — `PeriodType` enum: annual | interim | quarterly.
- `currency` — the reporting currency of the value, ISO 4217.
- `value` — `Decimal`.
- `filed_at` — publication timestamp where the provider supplies one, else `None`.
- `available_at` — timezone-aware UTC first-known timestamp; **required**, never `None`. This is
  the field every as-of query filters on.
- `revised_at` and `revision_sequence` — restatement timestamp and monotonic sequence number.
- `source` — provider/dataset identifier.
- `availability_imputed` — boolean flag, true when `available_at` was derived rather than observed
  (DEC-007), together with the imputation rule identifier used.

## Out of scope
The canonical line-item taxonomy and provider mappings (QNT-021); revision storage semantics
(QNT-022); currency conversion (QNT-023); Parquet persistence (QNT-024); the as-of query API
(QNT-025). No provider is called from this ticket.

## Acceptance criteria
- [ ] `trp.domain` exports a frozen `FundamentalValue` model and the `StatementType` and
      `PeriodType` enums; `mypy --strict` and `make check` pass.
- [ ] `available_at` is a required timezone-aware UTC `datetime`; constructing a record with a
      naive datetime, or with `available_at = None`, raises `ValidationError`.
- [ ] `value` is a `Decimal` and a `float` input is rejected rather than coerced; `currency` is
      validated as an uppercase ISO 4217 code.
- [ ] `available_at < period_end` is rejected as a data error, while `available_at >= period_end`
      is accepted without the model *assuming* the relation elsewhere — the invariant is asserted
      explicitly in the validator and covered by a test on each side of the boundary.
- [ ] `revision_sequence` is a non-negative integer with 0 reserved for the original filing;
      a record with `revision_sequence > 0` must carry `revised_at`, and one with
      `revision_sequence == 0` must not.
- [ ] `availability_imputed` is true if and only if an imputation rule identifier is present, and
      unit tests cover every invariant above with both an accepted and a rejected example.

## Technical notes
Per DEC-005 this is a Pydantic v2 frozen model: `Decimal` for the value, timezone-aware UTC for
`filed_at`, `available_at` and `revised_at`, and plain `date` for `period_end` because a period end
is a market-local calendar concept, not an instant.

The distinction between `filed_at` and `available_at` is the point of the whole record and must be
documented in the model docstring. `filed_at` is what the provider claims about publication;
`available_at` is our conservative answer to "from when was a researcher entitled to know this?".
They are frequently different and only `available_at` is load-bearing for correctness — as-of
queries (QNT-025) filter on `available_at` and must never fall back to `filed_at` or `period_end`.

Where no announcement timestamp exists, DEC-007 applies: impute late, as `period_end` plus a
documented per-market reporting lag, and set `availability_imputed`. This ticket defines the field
and the flag; it should also define the small value object or string identifier naming the rule
applied (e.g. `uk-annual-lag-90d`) so that QNT-035 can later measure how wrong the assumption was.
Do not bake a lag table into the model itself.

`available_at >= period_end` is expected in practice but must not be assumed silently anywhere: the
validator states it, and downstream code must not skip an `available_at` filter on the grounds that
`period_end` is already in the past. Note in the docstring that the reverse ordering can legitimately
appear in provider data for pre-announcements and is treated as an error to be investigated, not
quietly corrected.

Revision sequence monotonicity is a property of a *set* of records for the same
(security, statement, line item, period end, period type) key. The single-record validator can only
enforce the local rules above; the collection-level check (sequence starts at 0, increases by one,
and `revised_at` increases with it) belongs in a helper function in this module so QNT-022 can reuse
it rather than reimplement it.

## Dependencies
QNT-006 — the security master domain model and identifier conventions this record refers to.

## Risks
Getting the field set wrong here is expensive: every fundamental row written under a deficient
schema has to be re-derived from raw payloads, and any research result computed from it is void.
Mitigated by writing the schema before any ingestion exists, and by keeping raw payloads immutable
so re-derivation is always possible. A subtler risk is that `filed_at` and `available_at` get
conflated by a later contributor; mitigated by the docstring, the imputation flag, and the
time-travel suites from QNT-025 onwards.

## Testing requirements
`tests/domain/test_fundamental_model.py`. Invariant tests as listed in the acceptance criteria,
including mutation-raises tests for the frozen model, `Decimal`-not-`float` tests, and boundary
tests where `available_at` equals `period_end` exactly. Collection-level tests for the revision
sequence helper: a well-formed original-plus-two-revisions series passes; a series with a gap, a
duplicate sequence number, or a `revised_at` that goes backwards fails. No `timetravel` marker is
required here because this ticket exposes no data-access API, but the fixtures built here must be
reusable by the QNT-022 and QNT-025 time-travel suites and should be placed in a shared
`tests/fixtures/` module accordingly.

## Documentation requirements
`docs/DATA_MODEL.md` fundamentals section updated to point at `trp.domain` as the authoritative
definition, stating the `filed_at` versus `available_at` distinction and the revision-sequence
convention. A `DECISIONS.md` entry if the security-versus-entity subject choice or the imputation
rule identifier format constrains later work.

## Completion notes
_Not started._
