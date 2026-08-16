# QNT-064 — Run capture and reproducibility manifest

- **Ticket ID:** QNT-064
- **Status:** BACKLOG
- **Priority:** P2
- **Epic:** EPIC 10 — Research Experiment Registry

## Problem
`QUANT_PRINCIPLES.md` §4 is unambiguous: a result that cannot be regenerated is not evidence. In
practice reproducibility is lost through small omissions — an uncommitted working-tree change, a
data refresh between runs, a parameter passed on the command line and forgotten, an unseeded
shuffle. Each is invisible at the time and fatal months later. Capture has to be automatic, because
a manifest that depends on the researcher remembering to fill it in will be wrong precisely when it
matters.

## Objective
Capture a complete reproducibility manifest automatically for every research run, and support
re-running an experiment from its manifest such that the metrics come out identical.

## Scope
Manifest capture: git commit and dirty-tree state, dataset version and ingestion timestamps for
every input dataset read, full resolved parameter set, factor and universe definition versions,
random seed, library versions, and run start/end timestamps. Persistence of the manifest against the
experiment record, and a `rerun` path that reconstructs a run from a stored manifest.

## Out of scope
Metric and artefact storage (QNT-065); workflow enforcement (QNT-066); reproducing results across
different library major versions or a changed provider dataset — these are detected and reported,
not repaired.

## Acceptance criteria
- [ ] Every run persists git commit, working-tree cleanliness, resolved parameters, input dataset
      versions with ingestion timestamps, definition versions and random seed, with no manual step.
- [ ] A run started from a dirty working tree is recorded as such and is flagged as non-reproducible
      in the registry; it cannot be cited as evidence for a confirmatory conclusion.
- [ ] Re-running an experiment from its manifest on the same commit and data version reproduces the
      headline metrics exactly, asserted by an automated test over a small fixture experiment.
- [ ] A re-run whose inputs no longer match the manifest (different commit, changed dataset version)
      fails with a diff of what changed rather than silently producing different numbers.
- [ ] Seeds are recorded even where the current code is deterministic, so that later stochastic
      components inherit the discipline.

## Technical notes
Dataset versioning depends on the ingestion layer's fetch timestamps and raw payload immutability
(ARCHITECTURE) — the manifest references those rather than hashing large canonical files. Where a
cheap content hash is available for a partition, record it; the goal is detecting change, not
guaranteeing bit-identity of inputs.

Exact metric reproduction means exact: float summation order must be stable, so any parallelism in
the backtester needs a deterministic reduction. If that proves impossible, record a documented
tolerance in the manifest rather than quietly relaxing the test.

## Dependencies
QNT-063 — the experiment record the manifest attaches to.

## Risks
Capture that is too eager (hashing every Parquet file on every run) makes runs slow and gets
disabled; capture that is too lazy misses the field that mattered. Mitigated by referencing
ingestion metadata rather than rehashing, and by the re-run test which fails if capture is
insufficient.

## Testing requirements
`tests/experiments/test_manifest.py`: capture completeness against the required field list, the
dirty-tree flag, an end-to-end re-run producing identical metrics, and a mismatch case producing a
readable diff.

## Documentation requirements
`docs/RESEARCH_METHODOLOGY.md` gains a short section on what is captured automatically and what the
researcher must still write down. `QUANT_PRINCIPLES.md` §4 cross-references this ticket's manifest as
its implementation.

## Completion notes
_Not started._
