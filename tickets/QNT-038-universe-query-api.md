# QNT-038 — Universe membership query API

- **Ticket ID:** QNT-038
- **Status:** BACKLOG
- **Priority:** P1
- **Epic:** EPIC 6 — Historical Universe Engine

## Problem
Stored membership history is only useful if every consumer reaches it through an API that cannot
return today's constituents by accident. If the factor engine or backtester is free to read the
membership table directly, one convenient filter — "status is active", "valid_to is null" — silently
reintroduces the survivorship bias the schema exists to prevent, and nothing in the codebase would
flag it.

## Objective
Provide `members(universe, date)` and the surrounding query surface as the only supported way to
obtain a universe, reading historical constituent data exclusively, with membership changes over
time queryable and time-travel tests proving no future information leaks in.

## Scope
`src/trp/universe/query.py` exposing a `UniverseQuery` service over the QNT-037 storage:

- `members(universe, date, *, as_of=None) -> frozenset[str]` — the `security_id` set that was in
  the universe on `date`, according to what was known at `as_of`.
- `membership_changes(universe, start, end) -> Sequence[MembershipChange]` — additions and removals
  in a period, each with its effective date and source.
- `history(universe, security_id) -> Sequence[UniverseMembership]` — every spell for one security.
- `universes() -> Sequence[str]` — registered universe names with their date coverage.

Also in scope: caching of resolved member sets, typed errors for unknown universe names and for
dates outside a universe's documented coverage, and the tests below.

## Out of scope
Sourcing constituent history (QNT-039); rule-based universe construction (QNT-040); the
survivorship acceptance gate (QNT-041); universe-level filters such as size or liquidity screens,
which belong to the universe that defines them.

## Acceptance criteria
- [ ] `members(universe, date)` returns the set of `security_id`s whose membership spell contains
      `date` under the half-open convention, including securities that have since delisted, and
      excludes current constituents whose spell had not begun by `date`.
- [ ] Querying a date before a universe's first membership record raises a typed
      `UniverseCoverageError` naming the universe and its covered range, rather than returning an
      empty set that a caller would read as "no members".
- [ ] `membership_changes` over a period returns each addition and removal exactly once with its
      effective date and source, and reconstructing membership by applying the changes to
      `members(universe, start)` reproduces `members(universe, end)` exactly.
- [ ] Every public query method takes an explicit `as_of` (defaulting to "all knowledge") and never
      returns rows whose knowledge timestamp exceeds it, per QUANT_PRINCIPLES §1.
- [ ] Unknown universe names raise a typed error listing the registered names; no query path
      returns a silently empty result for a mistyped universe.
- [ ] Time-travel tests in `tests/timetravel/` pass and would fail if the implementation fell back
      to current membership.

## Technical notes
Two distinct time axes are in play and must not be conflated. `date` is the simulated calendar date
whose membership is being asked about; `as_of` is knowledge time — when we learned about that
membership. They differ whenever a provider backfills or corrects constituent history, and the
backtester needs both: it asks for the universe on the rebalance date, using only knowledge
available at that same date.

Query is a read over Parquet; DuckDB SQL with a `date >= valid_from AND (valid_to IS NULL OR date <
valid_to)` predicate reads more clearly than dataframe filtering here. Return `frozenset` so callers
cannot mutate a cached result.

Cache resolved member sets by `(universe, date, as_of)` — the backtester will call `members` on
every rebalance date across decades. Cache invalidation is trivial because canonical data is
rewritten wholesale rather than mutated.

The coverage error is deliberate friction. A universe sourced from 2005 onwards genuinely cannot
answer a 1998 question, and a research result quietly computed on an empty universe is worse than a
failed run.

## Dependencies
QNT-037 — supplies the membership schema and storage this API reads.

## Risks
The main risk is bypass: a consumer reading the Parquet directly gets no guarantees. Mitigated by
making the query service the documented entry point, keeping storage-layer readers internal to the
package, and having QNT-041 assert the guarantees end-to-end.

A second risk is over-eager caching returning a stale member set after a re-ingest during a long
session. Mitigated by keying the cache on the dataset version already carried by canonical storage.

## Testing requirements
`tests/universe/test_query.py` — membership on spell boundaries (first day in, last day in, day
after removal), re-entry, open-ended membership, unknown universe, out-of-coverage date, and the
changes-replay reconciliation.

`tests/timetravel/test_universe_query.py` (marker `timetravel`) — a fixture universe where a
security is added in 2018 and another removed in 2012 must, for a query date in 2015, include the
removed security's predecessor spell only where it applies and exclude the 2018 addition entirely;
a further test asserts that a membership row backfilled with a later knowledge timestamp is
invisible to a query with an earlier `as_of`.

## Documentation requirements
`docs/ARCHITECTURE.md` universe engine section documenting `UniverseQuery` as the sole supported
access path and the `date` versus `as_of` distinction. `docs/DATA_MODEL.md` cross-reference from
the universes section to the query API.

## Completion notes
_Not started._
