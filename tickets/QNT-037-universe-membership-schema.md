# QNT-037 — Universe membership schema and storage

- **Ticket ID:** QNT-037
- **Status:** BACKLOG
- **Priority:** P1
- **Epic:** EPIC 6 — Historical Universe Engine

## Problem
A universe expressed as a list of securities is a snapshot of today. Any research built on such a
list silently excludes every company that was a constituent in the past and has since been
delisted, acquired or removed on a quarterly review — the textbook mechanism of survivorship bias.
The platform has no place to record that a security *was* a member of a universe between two dates
and is not one now, so no historical universe can be reconstructed at all.

## Objective
Define and persist a time-indexed `universe_membership` record — universe name, `security_id`,
`valid_from`, `valid_to`, source — as the single storage substrate for every universe in the
system, with enforced invariants that make an inconsistent membership history unwritable.

## Scope
`src/trp/universe/` package created here: `membership.py` defining the `UniverseMembership` frozen
Pydantic v2 model and a `UniverseName` type; `invariants.py` holding the validation functions;
`storage.py` writing and reading Parquet under `data/canonical/universes/`, partitioned by universe
name; unit tests.

Fields per `docs/DATA_MODEL.md`:

- `universe` — universe name (for example `FTSE100`, `FTSE250`, `UK_ALL_ORDINARY`).
- `security_id` — internal immutable identifier from the security master.
- `valid_from` / `valid_to` — membership period, half-open, `valid_to = None` meaning currently a
  member.
- `source` — provenance of the membership claim (provider name, curated file, or the rule-based
  constructor that generated it).

Invariants enforced before write: no two records for the same `(universe, security_id)` may have
overlapping validity; `valid_to` must be later than `valid_from`; every `security_id` must resolve
in the security master; `universe` must be a registered name rather than a free-string typo.

## Out of scope
The query API (QNT-038); sourcing actual FTSE constituent history (QNT-039); rule-based universe
construction (QNT-040); the survivorship acceptance suite (QNT-041); any factor or backtest
consumption of universes.

## Acceptance criteria
- [ ] `UniverseMembership` is a frozen Pydantic v2 model using the half-open range convention fixed
      in QNT-006, with `valid_to = None` for open-ended membership; `mypy --strict` passes.
- [ ] Writing a set of records in which two rows for the same `(universe, security_id)` overlap
      raises a typed error naming both offending records; adjacent ranges that merely touch, and
      genuinely disjoint spells of membership for the same security, are both accepted.
- [ ] Records round-trip through `data/canonical/universes/` Parquet storage with dates, `None`
      `valid_to`, and `source` preserved exactly; a read-after-write test asserts equality of the
      full record set.
- [ ] Writing a record whose `security_id` is absent from the security master raises rather than
      creating an orphaned membership row.
- [ ] The writer is re-runnable: rewriting the same universe from the same inputs produces
      byte-identical partitions, and no code path mutates an existing row's `valid_to` in place
      outside the documented "close the open spell" helper.
- [ ] Unit tests cover overlap detection (identical, contained, straddling, touching, disjoint),
      re-entry after removal, and open-ended membership.

## Technical notes
Storage follows ARCHITECTURE: Parquet under `data/canonical/universes/`, one partition per universe
name, read via DuckDB or Polars. Membership histories are small — thousands of rows per universe —
so favour a single file per universe over date partitioning to avoid tiny-file proliferation.

Reuse the overlap-checking function written for QNT-007 rather than reimplementing interval logic;
the grouping key differs (`(universe, security_id)` instead of `(security_id, kind, exchange)`) so
the checker should already be parameterised by key, and if it is not, generalising it is part of
this ticket.

Re-entry matters: a company demoted from the FTSE 100 in 2015 and promoted again in 2019 has two
membership rows, not one merged span. The invariant is non-overlap, never uniqueness per
`(universe, security_id)`, and tests must pin that distinction so a later "deduplication"
optimisation cannot quietly collapse the spells.

Registering universe names centrally (an enum or a small registry module) keeps a typo from
creating a silent empty universe that a downstream query would report as "no members" rather than
as an error.

`source` is required, not optional. A membership row whose provenance is unknown cannot be
assessed for the coverage caveats that QNT-039 will document, and mixed-source universes need to be
separable after the fact.

## Dependencies
QNT-008 — canonical Parquet storage conventions and writer utilities that this schema persists
through.

## Risks
Choosing a storage layout or range convention that conflicts with the rest of the canonical layer
would require rewriting membership data after other universes are built on it. Mitigated by
reusing QNT-008's writer and QNT-006's range convention rather than inventing local variants.

A subtler risk is that the schema permits, but nothing enforces, honest provenance — a rule-based
universe and a curated index history are indistinguishable once written if `source` is used
loosely. Mitigated by requiring `source` and asserting its presence in the write-path tests.

## Testing requirements
`tests/universe/test_membership_model.py`, `tests/universe/test_membership_storage.py`. Include a
fixture universe containing at least one delisted security, one security with two disjoint spells
of membership, and one open-ended current member.

`tests/timetravel/test_universe_membership_storage.py` (marker `timetravel`): storing membership
history must not make future membership visible — a fixture where a security joins a universe in
2020 must be absent from any reconstruction of the universe as at 2019, exercised through the
storage reader directly so the guarantee is established at the storage layer and not only at the
query layer added in QNT-038.

## Documentation requirements
`docs/DATA_MODEL.md` universes section expanded with the concrete field list, the half-open range
convention, the non-overlap invariant, and the meaning of `source`. `docs/ARCHITECTURE.md` updated
to note the creation of the `trp.universe` package.

## Completion notes
_Not started._
