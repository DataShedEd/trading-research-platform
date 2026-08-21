# QNT-066 — Hypothesis–experiment–evidence–conclusion workflow

- **Ticket ID:** QNT-066
- **Status:** DONE
- **Priority:** P2
- **Epic:** EPIC 10 — Research Experiment Registry

## Problem
The schema and storage make the discipline *possible*; nothing yet makes it *happen*. The specific
failures the methodology guards against are all failures of sequence and memory: writing the
hypothesis after seeing the result, presenting an exploratory finding as confirmatory, and — most
corrosive — forgetting that this was the twentieth variant tried. A registry that records variants
but never counts them provides the raw material for self-deception with none of the correction.

## Objective
Enforce the four-artefact workflow: a hypothesis exists before an experiment runs, evidence is
attached to the run that produced it, a conclusion cites evidence and states weaknesses, and the
variant count per hypothesis is tracked and surfaced wherever a conclusion is read.

## Scope
Hypothesis records with their own identifiers and creation timestamps; state machine over designed →
running → completed → concluded (or abandoned); variant counting per hypothesis; classification of
each experiment as confirmatory or exploratory; a warning surfaced on any conclusion drawn from a
hypothesis whose variant count exceeds a documented threshold without an out-of-sample or holdout
run.

## Out of scope
Statistical multiple-testing corrections (recorded as a follow-up, not implemented here); automatic
holdout splitting; API and UI exposure (QNT-074, QNT-079).

## Acceptance criteria
- [x] An experiment cannot enter the running state without an existing hypothesis record created at
      an earlier timestamp; an experiment attached to a hypothesis created afterwards is
      automatically classified exploratory and cannot be marked confirmatory.
- [x] The variant count per hypothesis increments for every experiment run against it, including
      abandoned ones, and is returned with every conclusion.
- [x] A conclusion on a hypothesis with more than the documented threshold of variants and no
      out-of-sample or holdout run is recorded with a multiple-testing warning that cannot be
      cleared without recording such a run.
- [x] Conclusions require an explicit judgement (supported, not supported, inconclusive), a citation
      of the evidence run, and at least one recorded weakness.
- [x] State transitions are tested exhaustively, including every rejected transition.

## Technical notes
The threshold is a documented convention, not a statistical claim — its purpose is to make the count
impossible to ignore, per `RESEARCH_METHODOLOGY.md` rule 3. Record the number, show the number, and
let the researcher argue with it.

Parameter sensitivity (rule 4) belongs with the conclusion: where a parameter was chosen by search,
the conclusion should carry the ±50% perturbation result. This ticket requires the field; producing
the sensitivity run is the backtester's job.

## Dependencies
QNT-065 — evidence retrieval that conclusions cite.

## Risks
Enforcement strict enough to be meaningful will occasionally be inconvenient, and the researcher and
the platform author are the same person, so the rules can always be edited away. Mitigated by making
the rules cheap to satisfy honestly and by recording overrides rather than allowing silent bypass.

## Testing requirements
`tests/experiments/test_workflow.py`: the full transition matrix, hypothesis-timestamp ordering,
variant counting including abandoned runs, and the multiple-testing warning path.

## Documentation requirements
`docs/RESEARCH_METHODOLOGY.md` updated to state which rules are mechanically enforced and which
remain conventions, so the difference is never guessed at.

## Completion notes
2026-08-21. Enforcement lives in `trp.experiments.store.Registry` (shipped with QNT-063,
proven here): an experiment can only be created against an EXISTING hypothesis (the
sequence is structural), and a CONFIRMATORY classification is refused outright when the
hypothesis record post-dates the experiment — the same record is admissible as
exploratory, which is the honest downgrade rather than a block. The full 5x5 transition
matrix is tested including every rejected pair (rejection surfaces via the store's
transition rule or the record's own shape invariants — both are the system saying no).
Variant counting includes abandoned experiments (the denominator); the count is consulted
at every conclusion, and past VARIANT_WARNING_THRESHOLD (5, a documented convention to
argue with) with no out-of-sample run on record the conclusion is stamped with a
multiple-testing warning that ONLY an experiment tagged out-of-sample clears — tested
end-to-end including the clearance. Conclusions demand judgement + evidence-run citation
(+ the run must belong to THIS experiment) + >= 1 weakness; a dirty-working-tree run is
refused as confirmatory evidence. The rule-4 parameter_sensitivity field ships on the
Conclusion model; producing the perturbation runs stays the backtester's job. Multiple-
testing statistical corrections recorded as a follow-up, per ticket. Methodology doc now
points at trp.experiments as the executable form. EPIC 10 complete (QNT-063..066).
Tests (6) in tests/experiments/test_workflow.py; 844 green.
