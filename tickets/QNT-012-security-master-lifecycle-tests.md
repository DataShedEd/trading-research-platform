# QNT-012 — Security master lifecycle test suite

- **Ticket ID:** QNT-012
- **Status:** DONE
- **Priority:** P1
- **Epic:** EPIC 2 — Security Master

## Problem
QNT-006 to QNT-011 are each tested in isolation. The failures that matter most in a security master
are the ones that only appear when a company's whole history is played through: a rename followed by
a delisting, an acquisition of a security whose ticker was reused afterwards. Unit tests pass while
the composite behaviour is wrong.

## Objective
An end-to-end regression suite built on worked fixtures covering three complete company lifecycles,
asserting that resolution, point-in-time lookup, event application, and storage all behave correctly
across every stage.

## Scope
`tests/lifecycle/` containing shared fixtures and the end-to-end suite; fixture data as small
committed files under `tests/fixtures/security_master/` describing three companies:

1. **Failure** — a company that lists, trades, and delists on insolvency; no successor.
2. **Rename** — a company that changes name and ticker mid-life and continues trading, whose old
   ticker is later reassigned to an unrelated company.
3. **Acquisition** — a company acquired by another security in the master, ceasing to trade.

Each fixture states, as data, the expected resolution and status at a set of probe dates.

## Out of scope
Price or corporate-action data for these companies (Epic 3 fixtures build on these securities);
performance benchmarking; any production code change beyond bugs this suite uncovers.

## Acceptance criteria
- [x] Three lifecycle fixtures exist as committed data files with documented, hand-checked expected
      results at a minimum of five probe dates each.
- [x] For every probe date, the suite asserts resolution forward (identifier to `security_id`) and
      reverse (`security_id` to identifiers) match the fixture's expectations.
- [x] The reassigned-ticker case asserts that the old ticker resolves to the renamed company before
      reassignment and to the unrelated company afterwards, with no ambiguity error at any probe
      date.
- [x] A full round trip through QNT-008 storage — build master, write, read, re-run every assertion
      — produces identical results, proving persistence loses nothing.
- [x] Point-in-time assertions with varying `as_of` confirm that events are invisible before their
      `available_at`, including for the delisting and the acquisition.
- [x] The suite runs in the default `make test` run and its `timetravel`-marked subset runs under
      `uv run pytest -m timetravel`.

## Technical notes
Fixtures are the deliverable, not the assertions: express expected results as data (a table of
probe date, query, expected outcome) so that adding a case is adding a row rather than writing code.
Hand-check the expectations against the lifecycle narrative before automating them — a fixture
derived from the implementation's own output proves nothing.

Use synthetic companies with obviously fictional names and identifiers rather than real ones, so
that nothing here depends on provider licensing or on a real company's history being remembered
correctly. Keep the dates realistic in shape (a delisting on a trading day, a ticker change
effective at a month boundary) so that later calendar work in QNT-016 can reuse them.

Include at least one deliberately awkward case per fixture — a status change and an identifier
change on the same date, or a delisting effective the day after the last traded date — since
boundary handling under the half-open range convention is where this layer breaks.

This suite is the regression harness for Epic 2: subsequent epics that touch the security master
must leave it green, and it is the first thing to run when a downstream result looks wrong.

## Dependencies
QNT-010 — supplies the event application helpers the fixtures are built with.
QNT-011 — supplies the point-in-time API the `as_of` assertions exercise.

## Risks
A fixture suite that encodes the implementation's current behaviour rather than intended behaviour
becomes a change-detector rather than a correctness test. Mitigated by requiring expected values to
be hand-derived and reviewed before the code is run against them.

## Testing requirements
This ticket is itself the test suite. It must include `timetravel`-marked tests for the point-in-time
assertions, and the whole suite must pass with no network access and no data outside
`tests/fixtures/`.

## Documentation requirements
A short `tests/lifecycle/README.md` describing each fixture's narrative and how to add a fourth;
`CLAUDE.md` testing section updated to name this suite as the Epic 2 regression harness.

## Completion notes
2026-08-16. `tests/fixtures/security_master/lifecycles.json` (fixture data: four synthetic
companies — the rename narrative needs both the renamed company and the unrelated reuser —
with 23 hand-derived probes) plus `tests/lifecycle/` (builder, runner, README). Every probe
asserts three ways: built master, Parquet storage round-trip, and (where `as_of` present)
through `PointInTimeSecurityMaster` under the `timetravel` marker. Boundary cases pinned:
resolution on the ticker-change date itself (half-open: old ticker unknown, new one
resolves), knowledge preceding the event (change announced 2015-05-29, effective 06-01),
late-delivered delisting, acquisition visible at noon but not after 18:00 completion.
Building the fixtures surfaced two genuine ordering rules, now documented in the README:
a reused ticker can only be added after the event that frees it, and it must carry
`recorded_at` — a backfilled always-known reuse record makes historical knowledge views
see two owners at once (the aggregate rejects it). CLAUDE.md names this suite the Epic 2
regression harness. All checks green (116 tests).
