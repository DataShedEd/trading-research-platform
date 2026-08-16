# QNT-049 — Factor point-in-time test suite

- **Ticket ID:** QNT-049
- **Status:** BACKLOG
- **Priority:** P2
- **Epic:** EPIC 7 — Factor Engine

## Problem
Each factor ticket tests its own arithmetic, but look-ahead bias enters at the joins between
components — a fundamentals lookup that ignores `available_at`, a price series read without `as_of`,
a restatement that silently rewrites a two-year-old score. These defects produce correct-looking
factor values and cannot be detected by inspecting the values themselves.

## Objective
Build the time-travel suite that proves factor values at date *t* change only when information
available at *t* changes, including a restatement fixture that flows correctly through to factors,
and adopt it as the acceptance gate for Epic 7.

## Scope
`tests/timetravel/test_factor_point_in_time.py` and its fixtures. The suite covers every shipped
momentum, quality, value and composite definition and asserts:

- **Future data is inert.** Appending prices, filings, or corporate actions dated after *t* leaves
  every factor value at *t* byte-identical.
- **Restatements flow correctly.** A company restating an earlier period yields unchanged factor
  values for dates before the restatement's `available_at` and changed values after it.
- **Availability lag is respected.** A factor computed the day before a report becomes available
  uses the previous report; the day after, it uses the new one.
- **Universe consistency.** Cross-sectional transforms at date *t* standardise over the universe as
  at *t*, so a security not yet in the universe cannot influence another security's z-score.
- **Negative control.** A deliberately leaky factor implementation (reading fundamentals by period
  end rather than by `available_at`) fails the suite.

## Out of scope
Universe survivorship testing (QNT-041); backtest-level leakage scenarios (QNT-057); numerical
correctness of individual factors, which their own tickets cover.

## Acceptance criteria
- [ ] For every shipped factor and composite definition, a test asserts values at date *t* are
      unchanged when data dated after *t* is added to the fixture store.
- [ ] A restatement fixture demonstrates that factor values before the restatement's `available_at`
      use the original figures and values after it use the restated figures, for at least one
      quality and one value factor.
- [ ] A boundary test asserts the availability-lag behaviour on the day before and the day after a
      report's `available_at`.
- [ ] A negative-control leaky implementation fails at least three assertions in the suite, proving
      the suite can detect look-ahead.
- [ ] A cross-sectional test asserts that securities absent from the universe at *t* do not affect
      standardised values of securities present at *t*.
- [ ] The suite runs under the `timetravel` marker in CI on every change to `trp.factors`, and Epic 7
      completion is recorded as gated on it passing.

## Technical notes
Build the fixtures as a small synthetic canonical store — a handful of securities with prices,
corporate actions, and multi-period fundamentals including one restatement — rather than against
ingested provider data, so the suite is fast, deterministic, and runnable in CI without credentials.

The strongest assertion form is differential: compute the full factor panel at *t* against the
restricted store, then against the full store, and assert equality. It requires no knowledge of the
expected values and catches leaks in components nobody thought to test individually.

## Dependencies
QNT-044, QNT-045, QNT-046 — supply the factor definitions the suite exercises.
QNT-048 — supplies the composites whose scores must inherit the same guarantees.

## Risks
A suite built only on synthetic fixtures may miss leaks that appear with real provider quirks
(missing timestamps, imputed availability). Mitigated by adding a real-data smoke run under a
separate marker that skips cleanly when the canonical store is absent, and by requiring it for the
epic gate.

## Testing requirements
This ticket is itself a testing deliverable, under the `timetravel` marker, plus
`tests/factors/test_pit_negative_control.py` verifying the leaky implementation is detected. CI must
run the marker as a required check, and assertion messages must name the factor, the date, and the
offending security.

## Documentation requirements
`docs/QUANT_PRINCIPLES.md` §1 cross-referenced to this suite as the factor-layer enforcement
mechanism. A note in the factor authoring guide that any new definition must be added to this suite
before use in an experiment.

## Completion notes
_Not started._
