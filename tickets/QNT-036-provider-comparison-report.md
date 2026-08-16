# QNT-036 — Automated provider comparison report

- **Ticket ID:** QNT-036
- **Status:** BACKLOG
- **Priority:** P1
- **Epic:** EPIC 5 — Data Provider Bake-Off

## Problem
The bake-off's conclusions are worthless if they live in a hand-written table. A hand-edited
comparison drifts from the results it claims to summarise, cannot be regenerated when a provider's
data changes or a check is fixed, and offers no way to tell which numbers came from evidence and
which from someone's recollection. Since this report justifies an ongoing subscription cost and a
dependency the entire platform inherits, it must be reproducible from persisted artefacts on the
same terms QUANT_PRINCIPLES §4 demands of any research result.

## Objective
Generate the Results section of `docs/DATA_PROVIDER_EVALUATION.md` from persisted harness results:
per-criterion scores, links to evidence, illustrative failed checks, and a recommendation — written
by the generator, never by hand.

## Scope
`src/trp/bakeoff/report.py` plus a CLI entry point: read a run's persisted results (QNT-029) and
scores (QNT-030), render markdown into a clearly delimited generated region of
`docs/DATA_PROVIDER_EVALUATION.md`, and write nothing outside that region. Includes the summary
table, per-criterion breakdown per provider, evidence references, selected failed-check examples,
run provenance, and the recommendation section.

## Out of scope
Computing scores (QNT-030); running the harness (QNT-029); the desk-research provider notes and
pricing sections (QNT-028), which are hand-written and must be left untouched; making the purchase
decision, which remains the owner's.

## Acceptance criteria
- [ ] The generator writes only between explicit generated-region markers in
      `docs/DATA_PROVIDER_EVALUATION.md`; hand-written sections above and below are preserved
      byte-for-byte, and a test asserts this by round-tripping a document with hand-edited content
      in both regions.
- [ ] Regeneration is deterministic and idempotent: running the generator twice over the same run
      results produces an identical document, so a diff shows only genuine result changes.
- [ ] The report includes a per-provider summary with the weighted total, a per-criterion breakdown
      showing each criterion's score, weight and contribution, whether it was empirical or
      declared, and how many checks it was computed from — with `unmeasured` criteria shown as such
      rather than as zero.
- [ ] Every reported score links to its evidence: the checks behind it, and for failures the
      expected value, observed value, security, and a reference to the raw payload that produced
      the observation, so any claim can be traced without re-running anything.
- [ ] Illustrative failed checks are included per provider, selected deterministically (highest
      weighted criteria first, then a documented tie-break) rather than arbitrarily, with enough
      detail that a reader can judge whether the provider or the expectation was wrong.
- [ ] Run provenance is recorded in the generated region: run identifier, run timestamp, validation
      universe version, weight-file version, adapter versions, git commit, and the tier tested per
      provider; and the document states plainly that the section is generated and must not be
      hand-edited.

## Technical notes
`docs/DATA_PROVIDER_EVALUATION.md` already declares itself partly generated and reserves the
Results section for this ticket — the marker convention should make that boundary mechanical rather
than a matter of convention, so an accidental hand edit inside the region is detectable (a checksum
or a plain warning comment at the region head).

Presentation should reflect what the scores actually support. QNT-030's totals are ordinal, so lead
with the per-criterion breakdown and treat the aggregate as a summary, not a verdict: two providers
within a few points are not meaningfully separated, and the report should say so rather than imply
a ranking the evidence does not carry. Where a provider fails a near-veto criterion, that belongs at
the top of its section regardless of its total.

The recommendation section is generated from the scores plus the declared criteria, but it is a
recommendation to the owner, not a decision. State the recommended provider, the runner-up, the
specific evidence that separates them, the main uncertainty, and the monthly cost, and repeat the
owner-decision-gate note from QNT-028. Where the evidence is genuinely inconclusive, the generator
should say so rather than manufacturing a winner — encode that as an explicit condition, not as an
accident of formatting.

Include what was *not* measured as prominently as what was: securities that could not be fetched,
checks that errored, quota exhaustion during the run, and datasets outside the subscribed tier.
A comparison that silently omits its gaps is the failure mode this whole epic exists to avoid.

Keep the rendering simple — markdown tables generated from the result structures, no templating
framework — in keeping with `docs/ARCHITECTURE.md`'s preference for simple, inspectable components.
Timestamps in the report are timezone-aware UTC (DEC-005) and rendered with an explicit `Z`, and
scores are rendered from `Decimal` with a fixed, documented number of decimal places so the output
is stable across runs.

## Dependencies
QNT-030 — the scores and per-criterion breakdown the report renders. QNT-034 and QNT-035 — the
check results that supply the evidence and failure examples, without which the report has nothing
to say about the two highest-weighted criteria.

## Risks
A generated report is only as honest as its inputs, and a reader may treat a well-formatted table
as more authoritative than the underlying sample size warrants. Mitigated by surfacing check counts,
unmeasured criteria and run gaps in the report itself, and by presenting the breakdown ahead of the
total. A second risk is the generated region drifting from the hand-written sections around it —
for example pricing in the notes going stale relative to the cost criterion; mitigated by including
the verification date of declared inputs in the generated provenance block.

## Testing requirements
`tests/bakeoff/test_report.py` operating on synthetic run results and scores: marker-region
isolation with hand-edited content preserved, idempotent regeneration (generate twice, compare
bytes), correct rendering of unmeasured and capability-zero criteria, deterministic failed-check
selection, provenance block completeness, and the inconclusive-recommendation path. No harness run
and no provider involved. No `timetravel` marker applies — the report renders bake-off results
rather than serving historical queries.

## Documentation requirements
`docs/DATA_PROVIDER_EVALUATION.md` Results section replaced by the generated region with its
markers and a do-not-hand-edit warning, and its opening status line updated once a real run has
been published. The `src/trp/bakeoff/` README documents how to regenerate the report and how to
interpret each column, including the meaning of `unmeasured` and of a capability-based zero.

## Completion notes
_Not started._
