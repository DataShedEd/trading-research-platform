# QNT-074 — Factors, universes, backtests and experiments endpoints

- **Ticket ID:** QNT-074
- **Status:** BACKLOG
- **Priority:** P3
- **Epic:** EPIC 12 — Research API

## Problem
Research output is currently reachable only from Python. The terminal needs ranked factor scores and
backtest curves, and the LLM interface needs a deterministic query surface over experiments — and
both need the accompanying provenance. A factor score without its definition version, or a backtest
metric without its manifest, is a number with no meaning, and once it has been through an HTTP
response and into a chart, the missing context is unrecoverable.

## Objective
Expose read-only endpoints for factor scores, universe membership, backtest results and experiment
records, each response carrying the versions and manifest references that make the numbers
interpretable.

## Scope
`trp.api` routers for: factor scores for a security or universe `as_of` a date, factor definitions
and their versions, universe membership `as_of` a date, backtest results including metrics and
series, and experiment records with listing, filtering and comparison.

## Out of scope
Risk and signal endpoints (QNT-075); triggering backtests or creating experiment records over HTTP —
the API stays read-only; LLM tool definitions (QNT-080).

## Acceptance criteria
- [ ] Factor score responses include the factor definition version and the `as_of` date used, and
      universe membership responses are computed from time-indexed membership rather than current
      constituents.
- [ ] Backtest result responses reference the run manifest identifier, and metric responses state the
      cost assumptions and benchmark the metrics were computed under.
- [ ] Experiment endpoints support listing with the QNT-065 filters and multi-experiment comparison,
      and every conclusion returned carries its variant count and any multiple-testing warning.
- [ ] Series endpoints (equity curve, rolling statistics) support a date range and state the
      frequency of the returned series.
- [ ] All endpoints remain GET-only, and the route-table test from QNT-072 still passes.

## Technical notes
The variant count and multiple-testing warning must travel with the conclusion rather than being
available on a separate endpoint — the whole point of QNT-066 is that the count is unavoidable at the
moment a conclusion is read, including when it is read by a chart or an LLM.

Experiment comparison is a read of the QNT-065 comparison function; missing metrics stay missing in
the response and must not be serialised as zero or null-coerced into a number by the response model.

## Dependencies
QNT-072 — the application skeleton; QNT-057 — the backtest engine output being exposed; QNT-066 — the
experiment workflow whose records and warnings are surfaced.

## Risks
Provenance fields are the first thing dropped when a response looks verbose, and their absence is
invisible until a chart is wrong; mitigated by making them required fields in the response models so
omission is a validation error.

## Testing requirements
`tests/api/test_research_endpoints.py`: version and manifest fields present on every relevant
response, historical universe membership correctness, comparison with a metric missing from one
experiment, and the variant-count field on conclusions.

## Documentation requirements
OpenAPI descriptions explain the provenance fields and why they are mandatory; a short section in
`docs/RESEARCH_METHODOLOGY.md` noting that API consumers see the same variant counts as the registry.

## Completion notes
_Not started._
