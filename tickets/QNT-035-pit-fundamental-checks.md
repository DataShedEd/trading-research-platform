# QNT-035 — PIT fundamental and revision checks

- **Ticket ID:** QNT-035
- **Status:** BACKLOG
- **Priority:** P1
- **Epic:** EPIC 5 — Data Provider Bake-Off

## Problem
Point-in-time fundamental availability is one of the two highest-weighted criteria in the rubric,
and it is the one every vendor describes most loosely. "Historical fundamentals since 2000" almost
always means the current view of history: restated figures with no publication timestamps,
presented as though they had always been known. A platform built on that data produces value and
quality factors that appear to work and cannot. Meanwhile DEC-007's imputation parameters — the
reporting lags used when no announcement timestamp exists — are currently assumptions with no
empirical basis, and the bake-off is the natural opportunity to measure them.

## Objective
Implement the harness checks that establish, per provider, whether filing timestamps are present,
whether first-known availability can be reconstructed, whether restatements are distinguishable
from originals, and what the actual filing-lag distribution looks like per market.

## Scope
`src/trp/bakeoff/checks/fundamentals_pit.py`, registered against the QNT-029 check protocol:

- **Timestamp presence** — do fundamental records carry an announcement, filing or accepted date,
  and for what proportion of records and markets?
- **Availability reconstructibility** — can a defensible `available_at` be derived per QNT-020,
  and if only by DEC-007 imputation, is that recorded as such?
- **Restatement distinguishability** — for the universe's restatement cases, does the provider
  expose the original figure at all, or only the restated one? Are revisions separate records?
- **Filing-lag distribution** — measure observed lag between `period_end` and filing timestamp per
  market and period type, as evidence for or against DEC-007's imputation parameters.

## Out of scope
Corporate-action and price checks (QNT-034); scoring (QNT-030); the report (QNT-036); the canonical
fundamentals pipeline itself (Epic 4) — these checks measure provider data, not our transforms;
changing DEC-007's parameters, which would be a superseding decision entry made once the evidence
exists.

## Acceptance criteria
- [ ] The timestamp-presence check reports, per provider and market, the proportion of fundamental
      records carrying a usable publication timestamp, which field it came from, and whether the
      value is plausible (after `period_end`, before today, not a placeholder such as the period
      end repeated or an epoch date).
- [ ] The availability-reconstructibility check classifies each provider into a documented,
      ordered set of outcomes — genuine first-known timestamps, filing dates only, period end only
      (imputation required), or nothing usable — with per-market results and evidence, since this
      classification drives the rubric's highest-weighted fundamental criterion.
- [ ] The restatement check runs against the validation universe's restatement case and reports
      whether the original pre-restatement figure is retrievable, whether revisions appear as
      distinct records with their own timestamps, and whether querying the provider today silently
      returns only the restated value.
- [ ] The filing-lag check computes the distribution of (filing timestamp − `period_end`) per
      market and period type, reporting median and upper percentiles with sample sizes, and
      explicitly compares the observed upper percentile against the lag currently assumed by
      DEC-007, flagging where the assumption is not conservative enough.
- [ ] Every result carries evidence — the record, the field inspected, the observed value, and a
      raw payload reference — and a provider that does not support fundamentals at the subscribed
      tier yields a capability-based zero distinguishable from a tested failure.
- [ ] All checks run against fake-provider fixtures covering a provider with true first-known
      timestamps, one with filing dates only, one with period ends only, and one whose restatements
      are invisible, each producing the expected classification.

## Technical notes
This ticket is where QUANT_PRINCIPLES §1 meets commercial reality. The platform's correctness
guarantee is bounded by what the provider preserves: if no provider exposes original pre-restatement
figures, that is a finding to record honestly in the report and in `RESEARCH_METHODOLOGY.md`, not a
gap to paper over with imputation. The checks exist to make the bound explicit and measurable.

Distinguish carefully between the three timestamps that get conflated: `period_end` (a market-local
date), a filing or accepted date (when the document reached the regulator or the vendor), and true
first-known availability (when the information became public). Providers frequently label the second
as though it were the third; the check should record which field was inspected and its label
verbatim, so the report can show what was actually available rather than what it was called.

Placeholder detection matters more than it sounds. A filing date exactly equal to `period_end` for
every record is not a filing date, it is a default, and treating it as one would produce a dataset
that leaks up to months of future information while appearing fully point-in-time. Test for
suspicious uniformity — identical lag across all records, dates clustering on the first of the
month, epoch or far-future values — and report it as a distinct failure reason.

The filing-lag distribution is the most directly actionable output of this epic beyond the purchase
decision, because DEC-007's per-market lags are currently assumptions. Report percentiles rather
than means, since imputation must be conservative against the tail, not the centre: an imputation
lag at roughly the 90th percentile of observed lags is defensible, one at the median is not. Where
observed lags exceed the assumed lag, say so plainly — that is a superseding-decision trigger.

Checks read raw payloads or transport-level adapter output, never canonical data, so what is
measured is the provider. Timestamps in results are timezone-aware UTC (DEC-005); `Decimal` for any
value comparison in the restatement check.

## Dependencies
QNT-029 — the check protocol, result structure and harness that executes these checks and supplies
the validation-universe restatement expectations.

## Risks
Sample size is the main threat to the filing-lag evidence: a validation universe of a few dozen
securities gives a thin distribution, and per-market percentiles from small samples are weak
grounds on which to change DEC-007. Mitigated by reporting sample sizes alongside every percentile
and by allowing the lag check to run over a broader security set than the validation universe where
API quota permits. A second risk is misclassifying a provider that offers point-in-time data on a
separate product or tier not subscribed to; mitigated by recording the tier tested in the result
metadata and by QNT-028's research noting where such products exist.

## Testing requirements
`tests/bakeoff/test_fundamental_pit_checks.py` covering each check against the four fake-provider
fixtures described in the acceptance criteria, plus unit tests for placeholder detection, lag
percentile computation, and the classification ordering. Additionally
`tests/timetravel/test_pit_check_expectations.py` (pytest marker `timetravel`) asserting that the
availability values these checks derive, when fed into the QNT-020 record and queried as-of, never
yield a record visible before its derived availability — the check layer must not become a back
door around the point-in-time guarantee. No live provider calls in CI.

## Documentation requirements
`docs/DATA_PROVIDER_EVALUATION.md` scoring table rows for PIT fundamental availability and revision
history updated to name these checks and the classification outcomes they produce. If the measured
filing-lag distribution contradicts DEC-007's parameters, add a superseding `DECISIONS.md` entry
referencing DEC-007 with the evidence; do not edit DEC-007 in place. `RESEARCH_METHODOLOGY.md`
records the resulting limits on point-in-time claims for whichever provider is chosen.

## Completion notes
_Not started._
