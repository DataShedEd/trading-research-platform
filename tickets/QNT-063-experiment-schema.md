# QNT-063 — Experiment registry schema

- **Ticket ID:** QNT-063
- **Status:** BACKLOG
- **Priority:** P2
- **Epic:** EPIC 10 — Research Experiment Registry

## Problem
Research that lives in notebooks and chat history is not research: six months later nobody can say
which universe a result used, which factor version produced it, or how many variants were tried
before the good one appeared. `RESEARCH_METHODOLOGY.md` states the discipline; nothing yet encodes
it. Without a schema that makes the required fields structurally mandatory, they will be omitted
exactly when the result looks promising and the temptation to move on is greatest.

## Objective
Define the experiment record schema — hypothesis through conclusion — and choose its storage
backend, so that every experiment is describable before it is run and retrievable long after.

## Scope
Domain models for the experiment record: hypothesis reference and text, rationale, universe
definition, observation and holding periods, signal and factor definitions with versions, entry and
exit rules, portfolio construction, transaction-cost assumptions, benchmark, status, results
reference, conclusion, weaknesses, follow-ups. Storage backend selection and the write/read layer for
records. A `DECISIONS.md` entry recording the storage choice.

## Out of scope
Run capture and the reproducibility manifest (QNT-064); results and artefact persistence (QNT-065);
workflow enforcement and variant counting (QNT-066); any UI.

## Acceptance criteria
- [ ] The schema carries every field listed in `RESEARCH_METHODOLOGY.md` for hypothesis, experiment,
      evidence reference and conclusion, with hypothesis, universe, periods, factor versions,
      cost assumptions and benchmark all required at creation time.
- [ ] Conclusion, weaknesses and follow-ups are optional at creation and required before a record can
      move to a concluded status; a concluded record with no weaknesses recorded is rejected.
- [ ] The storage backend is chosen between Parquet, SQLite and PostgreSQL with the reasoning and
      consequences appended to `docs/DECISIONS.md` as a new entry referencing DEC-004.
- [ ] Records are round-trippable: writing and re-reading a fully populated record returns an equal
      object, and unknown fields from a future schema version fail loudly rather than being dropped.
- [ ] A record carries a schema version so later migrations can be detected.

## Technical notes
DEC-004 deferred PostgreSQL until something has genuinely transactional state; the registry is the
first candidate. The realistic choice for a single researcher is SQLite (transactional, zero
administration, one file, good enough concurrency) versus Postgres (heavier, but shared with paper
trading in Epic 15). Parquet is a poor fit here — records are mutated as conclusions are added, and
Parquet is an append-only analytical store. Whichever is chosen, results *series* stay in Parquet
(QNT-065) and only metadata lives in the transactional store.

Failed and abandoned experiments are never deleted; the schema needs statuses covering designed,
running, completed, concluded and abandoned, and abandonment requires a reason.

## Dependencies
QNT-050 — the backtest engine whose runs experiment records describe.

## Risks
A schema that is tedious to populate gets bypassed, and the registry becomes a partial record that
is worse than none because it looks complete. Mitigated by keeping required fields to those that
genuinely determine reproducibility and by generating what can be generated (QNT-064).

## Testing requirements
`tests/experiments/test_schema.py`: required-field validation, status-transition rules, round-trip
persistence, and rejection of a concluded record lacking weaknesses.

## Documentation requirements
New `DECISIONS.md` entry for the storage choice; `docs/RESEARCH_METHODOLOGY.md` updated to point at
the schema as the executable form of the four artefacts.

## Completion notes
_Not started._
