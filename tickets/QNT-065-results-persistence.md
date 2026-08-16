# QNT-065 — Results persistence and retrieval

- **Ticket ID:** QNT-065
- **Status:** BACKLOG
- **Priority:** P2
- **Epic:** EPIC 10 — Research Experiment Registry

## Problem
An experiment produces a mix of shapes: scalar metrics, time series (equity curve, drawdown,
rolling statistics), per-period holdings, and generated artefacts such as reports. Kept as loose
files they become unlinkable from the record that produced them; kept in the metadata store they
bloat it. And the point of a registry is comparison — showing three momentum variants side by side
is the operation that makes accumulated research useful, and it has to be a first-class query rather
than a bespoke script each time.

## Objective
Persist experiment results in a form matched to their shape, linked to the experiment record and its
manifest, and provide listing, filtering and comparison across experiments.

## Scope
Metric storage (scalars against the record), series and holdings storage as Parquet under
`data/derived/experiments/<experiment_id>/`, artefact storage with content addressing; retrieval API
for a single experiment's results; list and filter by hypothesis, universe, date range, status and
tags; a comparison function returning aligned metrics for a set of experiments.

## Out of scope
Workflow enforcement (QNT-066); API exposure (QNT-074); charting and terminal views (QNT-079);
automated statistical comparison or significance testing between experiments.

## Acceptance criteria
- [ ] Scalar metrics, time series, per-period holdings and generated artefacts each persist under the
      experiment identifier and are retrievable together with the manifest that produced them.
- [ ] Listing supports filtering by hypothesis, universe, status, tag and run date, and returns
      results in a stable documented order.
- [ ] Comparison returns a metric-by-experiment table over an arbitrary set of experiment ids,
      aligning metrics by name and marking metrics absent from some experiments as missing rather
      than zero.
- [ ] Results are immutable once written: re-running an experiment creates a new run under the same
      record instead of overwriting the previous run's results.
- [ ] Deleting an experiment record is not supported by the API; abandoning is a status change.

## Technical notes
Split by shape: transactional metadata in the QNT-063 store, bulk series in Parquet queried through
DuckDB (DEC-003). The store holds references to Parquet paths, never the series themselves.

Missing-versus-zero in comparisons matters more than it sounds — a strategy with no short exposure
and a strategy where short exposure was never computed must not read the same in a comparison table.

## Dependencies
QNT-064 — results are stored against the run manifest that reproduces them.

## Risks
Unbounded artefact growth on a single machine; mitigated by content addressing to deduplicate
identical artefacts and by documenting what belongs in the store versus what can be regenerated from
the manifest.

## Testing requirements
`tests/experiments/test_results.py`: round-trip of each result shape, filter and ordering tests, a
comparison test with a metric present in only some experiments, and an immutability test asserting a
second run does not overwrite the first.

## Documentation requirements
Storage layout documented in `docs/ARCHITECTURE.md` under the derived layer; retrieval and comparison
usage in the module docstring.

## Completion notes
_Not started._
