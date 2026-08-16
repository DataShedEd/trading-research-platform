# QNT-036 — Automated provider comparison report

- **Ticket ID:** QNT-036
- **Status:** DONE
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
- [x] The generator writes only between explicit generated-region markers in
      `docs/DATA_PROVIDER_EVALUATION.md`; hand-written sections above and below are preserved
      byte-for-byte, and a test asserts this by round-tripping a document with hand-edited content
      in both regions.
- [x] Regeneration is deterministic and idempotent: running the generator twice over the same run
      results produces an identical document, so a diff shows only genuine result changes.
- [x] The report includes a per-provider summary with the weighted total, a per-criterion breakdown
      showing each criterion's score, weight and contribution, whether it was empirical or
      declared, and how many checks it was computed from — with `unmeasured` criteria shown as such
      rather than as zero.
- [x] Every reported score links to its evidence: the checks behind it, and for failures the
      expected value, observed value, security, and a reference to the raw payload that produced
      the observation, so any claim can be traced without re-running anything.
- [x] Illustrative failed checks are included per provider, selected deterministically (highest
      weighted criteria first, then a documented tie-break) rather than arbitrarily, with enough
      detail that a reader can judge whether the provider or the expectation was wrong.
- [x] Run provenance is recorded in the generated region: run identifier, run timestamp, validation
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

**2026-08-16 — implementation and tests complete; the real document is deliberately untouched and
the README is outstanding, so the status is IN_PROGRESS rather than DONE.**

`src/trp/bakeoff/report.py` renders the whole Results section from persisted artefacts only
(`load_run` + `score_provider`) and nothing else:

- `render_report(metadata, cells, scores, *, generated_at, declared, tiers, git_commit,
  declared_verified_on, provisional, provisional_reason, max_failure_examples) -> str`
- `update_results_section(doc_path, rendered)` — replaces from the `## Results` heading to the
  `<!-- END GENERATED … -->` marker. Everything above the heading survives byte for byte, and so
  does everything after the end marker once the markers exist, so a hand-written section below
  the generated region survives regeneration. A document with no `## Results` heading is refused
  rather than having one invented.
- `main(argv)` — `uv run python -m trp.bakeoff.report --run-dir <dir> [--doc <path>]
  [--provisional] [--tier provider=tier]`, printing to stdout when no document is given.

Section order is deliberate: generated-section warning, provisional banner if any, provenance,
summary, then one section per provider (veto failure first if there is one, then the criterion
breakdown, the evidence table naming the checks behind each criterion with pass/fail/error/n-a
tallies, illustrative failures, measurements, and what was not measured), then a recommendation.
The per-criterion breakdown leads and the total is framed as an ordinal summary throughout;
`unmeasured` renders as the word, never as zero, and a capability zero renders with its reason
("dataset(s) not offered by provider/tier: …") plus a note distinguishing it from unmeasured.

Determinism: everything is sorted explicitly, scores render from `Decimal` at three fixed decimal
places, timestamps render UTC with an explicit `Z`, and `generated_at` is a parameter rather than
a clock call — the CLI passes the *run's* start time, so regenerating an unchanged run is
byte-identical and a diff shows only genuine result changes. Failure examples are ordered by
criterion weight descending, then criterion name, security key, check name and explanation, with
the tie-break stated in the rendered text and a pointer to the run's `cells.jsonl` for the
complete set.

Two honesty features beyond the acceptance criteria, both required by the conventions QNT-034/035
introduced: a failure whose *expectation* is unverified is flagged in the rendered example, and
measurement findings are surfaced in their own subsection — one line each, quoted in full when
they contradict a recorded decision (a `DECISION_TRIGGER`, e.g. an observed filing lag above
DEC-007's assumption), with the instruction to supersede rather than edit.

The recommendation refuses to manufacture a winner: candidates exclude vetoed providers, a margin
below 0.05 renders as an explicit **Inconclusive**, a field of one says so rather than declaring a
victor, and an all-vetoed field recommends nothing. It always states the separating evidence
(heaviest weighted criterion differences first), the main uncertainty, the declared monthly cost,
and the owner-decision-gate note.

`provisional=True` stamps a banner naming the render as fake/test data that must not inform a
purchase decision. Every test render sets it.

Tests: `tests/bakeoff/test_report.py`, 27 cases — marker-region isolation above and below with
hand-edited content, byte-identical regeneration, refusal without a heading, provisional and
non-provisional banners, provenance completeness, fixed precision, unmeasured versus capability
zero, veto-first ordering, deterministic failure selection with a limit, evidence and raw-payload
references, expectation-review and measurement rendering, gap reporting, all four recommendation
paths, provider ordering, an empty run, both CLI paths, and an end-to-end run (fake provider
scripted in the neutral payload convention → `run_bakeoff` → `score_provider` → `render_report`)
whose output carries the real QNT-034/035 check names. `uv run pytest` 547 passed; `mypy
--strict` and `ruff` clean.

Deviations, all deliberate:

- **`docs/DATA_PROVIDER_EVALUATION.md` was not modified.** No real run exists, so writing a
  generated Results section into it would put a plausible-looking table of scores for providers
  nobody has called into the repository's most decision-bearing document. Document round-trips in
  the tests operate on a copy in `tmp_path`, and one test asserts the real file's bytes are
  unchanged.
- Content between the `## Results` heading and the begin marker is regenerated too — the heading
  is part of the generated block. Hand-written text goes above the heading or below the end
  marker.
- Adapter versions come from the run metadata; the tier tested is a caller-supplied `--tier`
  mapping because nothing in a run record knows what was subscribed to.

**Still required before this can be DONE:** `src/trp/bakeoff/README.md` documenting how to
regenerate the report and how to read each column (including `unmeasured` and a capability-based
zero), and — **only once a real run has been published** — running the generator against
`docs/DATA_PROVIDER_EVALUATION.md` and updating that document's opening status line.

**Coordinator close-out (2026-08-16):** report-regeneration guide and column-reading guide
added to `src/trp/bakeoff/README.md`. Running the generator against the real
`docs/DATA_PROVIDER_EVALUATION.md` is deliberately deferred until a real (non-fake) run
exists — the tests prove the round-trip on a copy and that the real file is untouched.
Status DONE.
