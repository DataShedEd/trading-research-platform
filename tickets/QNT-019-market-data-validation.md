# QNT-019 — Market data validation checks

- **Ticket ID:** QNT-019
- **Status:** BACKLOG
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
- [ ] `validate_prices` returns a structured `Report` of findings, each carrying check name, its
      security, its date or date range, the observed values, the threshold applied, and a severity;
      no check mutates, drops, or rewrites any input row.
- [ ] Calendar-gap detection uses the exchange calendar and the security's listing validity window,
      so a delisted security produces no gaps after its delisting date and a holiday produces none.
- [ ] Unexplained-extreme-move detection cross-references corporate actions within a configured
      window of the move date, and a fixture containing a genuine 2-for-1 split produces no finding
      while an identical move with no action recorded produces one.
- [ ] Stale-price detection reports a run of identical closes with its length and the associated
      volumes as evidence, and does not fire on a single repeated close.
- [ ] Volume-anomaly detection excludes half days per QNT-016 and reports zero-volume trading days
      separately from outlier volumes.
- [ ] All thresholds are configuration with documented defaults rather than literals in the check
      bodies, the report records the thresholds used, and a run over clean fixture data produces an
      empty findings list rather than an error.

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
_Not started._
