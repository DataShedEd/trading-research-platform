# QNT-041 — Universe survivorship test suite

- **Ticket ID:** QNT-041
- **Status:** BLOCKED
- **Priority:** P1
- **Epic:** EPIC 6 — Historical Universe Engine

## Problem
Survivorship bias is invisible in its own output. A universe built from today's constituents
returns plausible-looking security sets, produces backtests that run cleanly, and yields results
that are simply wrong by a margin nobody can see. Unit tests written alongside each component check
that the component does what its author intended; none of them proves the property that actually
matters — that a historical universe contains the companies that failed.

## Objective
Build the adversarial test suite that proves the universe engine is free of survivorship bias
end-to-end, and adopt it as the acceptance gate for Epic 6: the epic is not complete until this
suite passes.

## Scope
`tests/timetravel/test_universe_survivorship.py` and supporting fixtures. The suite asserts, over
both index universes (QNT-039) and the rules-based universe (QNT-040):

- **Failed companies are present.** A historical query returns companies that later collapsed, were
  acquired, or delisted — named explicitly, with the expected membership dates recorded in the
  fixture.
- **Future members are absent.** Current constituents whose membership began after the query date
  do not appear.
- **Removal is respected.** A company removed at an index review is absent from queries after the
  effective date and present before it.
- **No current-list fallback exists.** A mutation-style check: with historical membership records
  restricted to a subset, the query must fail or return the restricted result, never quietly
  substitute a current list.
- **Delisted securities survive round-trips.** Membership, security master resolution, and the
  universe API all continue to return a delisted `security_id` long after its delisting.

Also in scope: a documented list of the named "known casualties" used as fixtures, and a
`make survivorship` (or equivalent) target running the suite alone.

## Out of scope
Factor and backtest leakage tests (QNT-049, QNT-057); price and fundamentals point-in-time tests
belonging to their own epics; performance benchmarking of universe queries.

## Acceptance criteria
- [ ] A test asserts that a FTSE 100 query for a date in 2012 includes named companies that
      subsequently failed or were acquired, and the test fails if any is missing.
- [ ] A test asserts that securities which joined an index after the query date are excluded, using
      at least one company that is a current constituent.
- [ ] A test asserts that a company removed at a known index review is present the day before the
      effective date and absent the day after.
- [ ] A negative-control test proves the suite has teeth: a deliberately survivorship-biased
      universe implementation (a test double returning current members regardless of date) fails at
      least three assertions in the suite.
- [ ] The rules-based UK universe is covered by the same assertions, including that a company
      delisted mid-period appears for the period it was listed and not afterwards.
- [ ] The suite runs under the `timetravel` marker in CI on every change to `trp.universe`, and the
      epic's completion is recorded as gated on it passing.

## Technical notes
The negative control is the most important test in the suite. Without it, a suite that passes tells
you nothing about whether it *could* fail — a query returning current membership would pass any
assertion whose expected set happens to overlap. Implement it as a `SurvivorshipBiasedUniverse` test
double and assert on the count of failing assertions, not merely that something failed.

Prefer named companies with dates over statistical assertions. "The 2012 universe contains at least
N securities that are no longer listed" is weaker than naming specific casualties, because it can
be satisfied by an unrelated set and it degrades silently as data changes. Where the fixtures depend
on real ingested data that may be unavailable in CI, keep a small committed fixture mirroring the
same shape and run the real-data assertions under a separate marker that skips cleanly when the
canonical store is absent — but document that the epic gate requires the real-data run.

The "no current-list fallback" check is best expressed by restricting the fixture data rather than
by inspecting code: if the implementation is reading a current list from anywhere, restricting
historical membership will not change its answer.

This suite is an acceptance gate, so its failure mode should be legible. Assertion messages should
name the universe, the query date, and the specific missing or unexpected `security_id` with its
company name, so a failure is diagnosable without opening the fixtures.

## Dependencies
QNT-038 — supplies the query API the suite exercises.
QNT-039 — supplies the index constituent history the named-casualty assertions rely on.

## Risks
Fixtures naming real companies may become brittle if the underlying data source changes its
coverage, producing failures that read as bugs but are data-availability changes. Mitigated by
distinguishing committed-fixture tests from real-data tests, and by assertion messages that make
the cause obvious.

The opposite risk is a suite weakened over time to keep CI green. Mitigated by the negative control,
which fails loudly if the assertions have been relaxed into vacuity, and by recording the gate in
the epic documentation.

## Testing requirements
This ticket *is* a testing deliverable; the suite lives in `tests/timetravel/` under the
`timetravel` marker. Additionally, `tests/universe/test_survivorship_negative_control.py` verifies
that the biased test double is detected. CI must run the `timetravel` marker as a required check.

## Documentation requirements
`docs/QUANT_PRINCIPLES.md` §2 cross-referenced to this suite as the enforcement mechanism.
`docs/RESEARCH_METHODOLOGY.md` note that any new universe must be added to this suite before it is
used in an experiment. A short section in the Epic 6 documentation recording the acceptance gate and
the list of known-casualty fixtures.

## Completion notes
_Not started._

**BLOCKED (2026-08-16):** the acceptance gate needs real FTSE membership data (QNT-039).
The survivorship mechanics are already proven on fixtures
(tests/timetravel/test_universe_membership.py); this ticket re-proves them on real data.
