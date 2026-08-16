# QNT-019 — Market data validation checks

- **Ticket ID:** QNT-019
- **Status:** DONE
- **Priority:** P1
- **Epic:** EPIC 3 — Market Data

## Problem
Provider price data contains missing days, stale repeated closes, decimal-point errors, and moves of
tens of percent with no corresponding corporate action. Each of these produces a plausible-looking
factor value and an unreliable backtest. Nothing currently inspects the canonical price data for
these conditions, and a check that silently repairs them would be worse than none.

## Objective
Automated data-quality checks over canonical prices, corporate actions, and calendars that produce
an evidence-bearing report of warnings, making no changes to the data.

## Scope
`src/trp/canonical/validation/` providing a check registry and a `validate_prices(...) -> Report`
entry point, with the following checks:

- **Calendar gaps** — trading days per the QNT-016 calendar with no bar, within a security's
  listing validity window
- **Zero or negative prices** — bars that reached storage despite QNT-013's invariants, or nulls
- **Unexplained extreme moves** — a close-to-close move beyond a configured threshold with no
  corporate action within a small window of the date
- **Stale prices** — a close repeated unchanged for more than a configured number of consecutive
  trading days, with volume considered
- **Volume anomalies** — zero-volume trading days, and volume beyond a configured multiple of a
  trailing median, excluding half days

Plus a report model and a rendered summary suitable for reading in a terminal.

## Out of scope
Automatic correction or exclusion of any row; provider reconciliation across sources (Epic bakeoff);
fundamentals validation (Epic 4); alerting or scheduling.

## Acceptance criteria
- [x] `validate_prices` returns a structured `Report` of findings, each carrying check name, its
      security, its date or date range, the observed values, the threshold applied, and a severity;
      no check mutates, drops, or rewrites any input row.
      _`ValidationReport` is a frozen model holding a tuple of frozen `Finding`s; a test asserts the
      input frame is `equals`-identical after a run that fires every check._
- [x] Calendar-gap detection uses the exchange calendar and the security's listing validity window,
      so a delisted security produces no gaps after its delisting date and a holiday produces none.
      _Good Friday/Easter Monday 2020 and weekends produce nothing; a missing Tuesday is reported
      with its date. Gaps are grouped into runs contiguous in *trading* days, not calendar days._
- [x] Unexplained-extreme-move detection cross-references corporate actions within a configured
      window of the move date, and a fixture containing a genuine 2-for-1 split produces no finding
      while an identical move with no action recorded produces one.
      _The unrecorded case is reported at ERROR naming the ratio it resembles ("an unrecorded
      2-for-1 split"), which is the split-inversion detector QNT-015's risks ask for._
- [x] Stale-price detection reports a run of identical closes with its length and the associated
      volumes as evidence, and does not fire on a single repeated close.
      _A run with no volume at all is raised to ERROR: that is a provider carrying the last print
      forward, not a quiet stock._
- [x] Volume-anomaly detection excludes half days per QNT-016 and reports zero-volume trading days
      separately from outlier volumes.
      _Two separate checks, `zero_volume` and `volume_outlier`. Half days are excluded from
      `volume_outlier` only; a zero-volume half day is still reported, with the half day named in
      its evidence so it can be dismissed at a glance. Suppressing it outright would have hidden a
      genuinely suspended line that happened to fall on Christmas Eve._
- [x] All thresholds are configuration with documented defaults rather than literals in the check
      bodies, the report records the thresholds used, and a run over clean fixture data produces an
      empty findings list rather than an error.
      _`ValidationThresholds`, a frozen model with a docstring per field, stored on the report.
      `counts_by_check` carries an explicit zero for every check so a clean run is distinguishable
      from a check that never executed._

## Technical notes
Warnings, not fixes. The rule in `CLAUDE.md` and `docs/QUANT_PRINCIPLES.md` is no silent data
coercion: a check that quietly forward-fills a gap or clips an outlier destroys the evidence that
something is wrong with the source, and the resulting dataset looks clean while being less
trustworthy than the dirty one. Every finding therefore carries enough evidence for a human to
adjudicate, and adjudication decisions belong in exclusion lists recorded with the experiment, not
in this module.

Checks are set-based over Polars or DuckDB rather than per-row Python: the full canonical price set
is tens of millions of rows and a row-wise implementation will be unusable. Write each check as a
function from frames to findings so it can be tested in isolation on a small fixture.

The extreme-move check is the one with a real false-positive rate. A 30% single-day move is
sometimes a real event (a takeover approach, a profit warning) and sometimes a missing corporate
action or a decimal error. Its purpose is to produce a short list worth looking at, so tune the
default threshold for a manageable finding count and report the observed distribution rather than
suppressing findings.

Corporate-action cross-referencing must respect `available_at`: a check run reproducing a historical
state should use the actions known as at that date. Accept an optional `as_of` and default it to
"now" for routine data-quality runs.

## Dependencies
QNT-015 — supplies corporate-action-derived factors used to explain extreme moves.
QNT-016 — supplies the trading calendars gap and half-day detection require.
QNT-018 — supplies the partitioned price store the checks read.

## Risks
A noisy report gets ignored, which is the same outcome as having no checks. Mitigated by tuning
defaults against real ingested data before the ticket is closed, by separating severities, and by
recording the finding count per check so a sudden increase after an ingestion is itself the signal.

## Testing requirements
`tests/canonical/test_validation.py` plus `tests/timetravel/test_validation_timetravel.py` (pytest
marker `timetravel`). One fixture per check with both a firing and a non-firing case; a clean-data
fixture producing no findings; a fixture asserting no input frame is modified by any check. The
`timetravel` test asserts that a validation run with an `as_of` does not use corporate actions
published after that timestamp to explain a move.

## Documentation requirements
`docs/DATA_MODEL.md` or a new `docs/DATA_QUALITY.md` documenting each check, its default thresholds,
and how to interpret its findings. The no-silent-fixes policy stated explicitly in the module
docstring.

## Completion notes

**2026-08-16 — done. Defaults remain untuned against real data; see below.**

Delivered `src/trp/canonical/price_validation.py` (a single module rather than a
`canonical/validation/` package — six checks and a report model do not yet justify a package, and
the module is the natural sibling of `price_store.py`). Entry points `validate_prices(frame, ...)`
and `validate_bars(bars, ...)`; each check is also a public pure function taking a frame and
returning findings, so it can be exercised on a small fixture in isolation. Output is a frozen
`ValidationReport` with `to_frame()` and `to_markdown()`. Tests:
`tests/canonical/test_price_validation.py` (45) and
`tests/timetravel/test_price_validation_timetravel.py` (3), all passing; `mypy --strict` and `ruff`
clean. Test file names follow the module rather than the ticket's `test_validation.py`, to avoid
colliding with the fundamentals validation suite Epic 4 will add.

Checks implemented: `non_positive_price`, `calendar_gap`, `extreme_move`, `stale_price_run`,
`zero_volume`, `volume_outlier`, `adjustment_warning`, plus three diagnostics
(`listing_unknown`, `calendar_unavailable`, `calendar_range_clamped`) so that a check which *could
not run* is visible in the report instead of being indistinguishable from a check that found
nothing. Nothing raises: an unsupported MIC or an out-of-range window becomes a finding.

**DEC-009 is surfaced here as the decision requires.** `check_adjustment_warnings` lifts
`AdjustmentComputation.provenance.warnings` into the report, so a security with an unadjusted rights
issue is named in the data-quality output rather than only in a provenance blob. The `timetravel`
test additionally pins that this warning is itself point-in-time: a rights issue the vendor had not
yet published does not retrospectively appear in a reproduction of an earlier state.

**Two judgement calls worth review:**

1. *The extreme-move bound is inclusive* (`|move| >= threshold`, default 50%), not strict. An
   unrecorded 2-for-1 split lands on exactly -50%, so a strict comparison would let the single most
   common case this check exists to catch fall one step outside the test. This was found by the test
   fixture, not by reasoning — the first implementation used `>` and silently returned nothing for
   the split fixture.
2. *Dividends do not suppress an extreme-move finding.* Only structural actions (split, rights
   issue, merger, delisting) explain a move; a dividend near the date is attached to the finding as
   evidence instead. An ordinary dividend cannot cause a 50% move, and letting one suppress the
   finding would silence exactly the cases worth adjudicating. This is configurable
   (`explaining_action_types`).

Arithmetic is exact throughout: the threshold test is expressed as multiplication and comparison so
Polars evaluates it on Decimals without dividing, and the move itself is derived in `Fraction` for
the flagged rows only. The one non-exact step is the trailing volume median, which is floored to
whole shares before comparison — integer arithmetic, marginally more sensitive, which is the safe
direction for a warning-only check. No float64 anywhere (DEC-005).

**Outstanding, and the reason to revisit this ticket after the first real ingestion:** the risk
section asks for the defaults to be tuned against real ingested data before closing, and no real
data has been ingested yet. The defaults (50% move, 5-day stale run, 20x volume) are reasoned
starting points validated only against hand-built fixtures. The observed finding-count distribution
per check should be reviewed on the first full backfill, and `counts_by_check` exists to make that
review a one-liner.
