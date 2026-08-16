# QNT-066 — Hypothesis–experiment–evidence–conclusion workflow

- **Ticket ID:** QNT-066
- **Status:** BACKLOG
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
- [ ] An experiment cannot enter the running state without an existing hypothesis record created at
      an earlier timestamp; an experiment attached to a hypothesis created afterwards is
      automatically classified exploratory and cannot be marked confirmatory.
- [ ] The variant count per hypothesis increments for every experiment run against it, including
      abandoned ones, and is returned with every conclusion.
- [ ] A conclusion on a hypothesis with more than the documented threshold of variants and no
      out-of-sample or holdout run is recorded with a multiple-testing warning that cannot be
      cleared without recording such a run.
- [ ] Conclusions require an explicit judgement (supported, not supported, inconclusive), a citation
      of the evidence run, and at least one recorded weakness.
- [ ] State transitions are tested exhaustively, including every rejected transition.

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
_Not started._
