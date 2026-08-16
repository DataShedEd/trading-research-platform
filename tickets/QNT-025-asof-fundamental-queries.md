# QNT-025 — As-of fundamental query API and time-travel tests

- **Ticket ID:** QNT-025
- **Status:** BACKLOG
- **Priority:** P1
- **Epic:** EPIC 4 — Fundamental Data

## Problem
Everything Epic 4 has built so far is inert until research code can ask for it, and the moment it
can, the leak risk becomes real. A query that forgets an `available_at` filter, silently falls back
to `period_end`, or returns the newest revision regardless of the requested date will produce a
backtest that looks excellent and means nothing. Worse, a time-travel test suite that never fails
gives false confidence: a suite asserting "no rows returned with `available_at > as_of`" passes
trivially against an empty result set or a query that filters correctly by accident.

## Objective
Provide the point-in-time fundamentals query API — the only supported route from research code into
the fundamentals dataset — and a time-travel test suite that is itself proven to detect leakage.
This ticket is the acceptance gate for Epic 4.

## Scope
`src/trp/canonical/fundamentals/queries.py`: a `fundamentals(security_ids, line_items, as_of, ...)`
function (with optional `period_type`, period range, statement and target-currency arguments)
returning, for each security and period, the latest-known value as at `as_of`; the DuckDB/Polars
implementation over the QNT-024 dataset; and `tests/timetravel/` suites including a deliberately
corrupted fixture proving the tests catch leakage.

## Out of scope
Factor construction and ratio derivation (Epic 8); price-side as-of queries (Epic 3); the universe
engine's `members(universe, date)` (Epic 6); any caching layer — correctness first, and the
dataset is small enough that caching is premature.

## Acceptance criteria
- [ ] `fundamentals(...)` requires an explicit `as_of` argument with no default, and returns, per
      (security, statement, line item, period), exactly one row: the highest `revision_sequence`
      whose `available_at <= as_of`, with periods having no such row omitted rather than filled.
- [ ] The returned frame carries the provenance fields a researcher needs to trust it —
      `available_at`, `revision_sequence`, `availability_imputed`, reporting `currency` and
      `source` — so a result can be audited without a second query.
- [ ] It is structurally impossible to bypass the filter: the module exposes no unfiltered public
      read of the fundamentals dataset, and the `as_of` predicate is applied in one place that
      every query path goes through.
- [ ] A `timetravel`-marked suite asserts, across the restatement fixture from QNT-022 and a
      multi-period fixture, that no returned row has `available_at > as_of`, that a query dated
      between original filing and restatement returns the original figures, and that results are
      unchanged by rows added to the dataset with later availability.
- [ ] Test-the-test: a deliberately corrupted fixture (a row whose `available_at` has been moved
      earlier than the truth, and a variant query implementation that filters on `period_end`
      instead of `available_at`) causes the time-travel assertions to **fail**, and this is
      asserted in CI — a green suite against the corrupted fixture is itself a test failure.
- [ ] Requesting an `as_of` earlier than the dataset's earliest availability returns an empty
      result rather than raising, and requesting an unknown line item raises rather than returning
      silently empty — the distinction is documented and tested.

## Technical notes
`docs/QUANT_PRINCIPLES.md` §1 requires that every historical query API take an explicit `as_of` and
never return rows with `available_at > as_of`; this is the reference implementation of that rule
for fundamentals, and Epic 3's price queries should follow the same shape.

"Latest known as at `as_of`" is a per-key argmax over `available_at`/`revision_sequence`, which
expresses cleanly as a DuckDB window function over the Parquet dataset (DEC-003). Push the
`available_at <= as_of` predicate into the scan so partition pruning from QNT-024 still applies,
and keep the single choke point for that predicate obvious in the code — a reviewer should be able
to find every place `as_of` is applied in one grep.

Note the trap the API must avoid: filtering on `period_end <= as_of` looks equivalent and is not.
A December 2017 annual result is not knowable in January 2018. Only `available_at` is load-bearing,
and DEC-007 imputation means it may be conservatively late — never substitute `filed_at`, which is
frequently absent, and never fall back to `period_end` when `available_at` is null, because
QNT-020 makes it non-nullable precisely so that fallback cannot exist.

Where a target currency is requested, conversion is delegated to QNT-023 and inherits the same
`as_of`, so an FX rate published after `as_of` can never be used.

The test-the-test requirement deserves emphasis: mutation-style verification is the only evidence
that a passing suite means anything. Implement it as an explicit test that runs the time-travel
assertions against the corrupted fixture and asserts they raise, rather than as a manual procedure
someone is trusted to have performed. Keep the corrupted fixture clearly named and physically
separate from the good fixtures so it can never be picked up by a normal test run.

As the Epic 4 acceptance gate, this ticket should end with the full fundamentals path demonstrated
end to end on fixture data: normalise (QNT-021) → classify revisions (QNT-022) → write (QNT-024) →
query as-of (this ticket), with `make check` green.

## Dependencies
QNT-022 — revision semantics and the restatement fixture the as-of behaviour is defined against.
QNT-024 — the stored dataset and partitioning the query reads.

## Risks
A query API that is correct today can be bypassed tomorrow by a contributor reading the Parquet
files directly, reintroducing leakage outside this module's guarantees. Mitigated by making this
the only public read path, saying so in `CLAUDE.md`, and keeping the raw dataset location an
implementation detail. The second risk is over-reliance on the time-travel suite as proof of
correctness when it only covers the fixtures written for it; mitigated by the corrupted-fixture
check and by extending the suite whenever a new availability edge case is found.

## Testing requirements
`tests/canonical/test_fundamental_queries.py` for API behaviour, argument validation, empty-versus-
raise semantics, and provenance columns. `tests/timetravel/test_fundamental_asof.py` (pytest marker
`timetravel`) for the leakage assertions, and
`tests/timetravel/test_fundamental_asof_detects_leakage.py` (also marked `timetravel`) for the
test-the-test case using the corrupted fixture and the deliberately wrong query variant. Confirm
`make check` runs the `timetravel` marker in CI rather than deselecting it.

## Documentation requirements
`docs/DATA_MODEL.md` and `docs/ARCHITECTURE.md` updated to name this module as the only supported
fundamentals read path. `docs/RESEARCH_METHODOLOGY.md` gains a short section on how to query
fundamentals point-in-time correctly, including the `period_end`-versus-`available_at` trap and the
meaning of the `availability_imputed` flag in results. `CLAUDE.md` conventions note that direct
Parquet reads of the fundamentals dataset are not permitted in research code.

## Completion notes
_Not started._
