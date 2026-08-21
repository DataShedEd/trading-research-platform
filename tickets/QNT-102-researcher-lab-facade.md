# QNT-102 — The researcher lab facade: five-line experiments, one-page evaluation

- **Ticket ID:** QNT-102
- **Status:** DONE
- **Priority:** P1
- **Epic:** EPIC 13 — Research Terminal (interaction layer)

## Problem
The platform's guarantees are strong but its interaction surface is hostile: designing an
experiment takes ~40 lines of registry plumbing, and evaluating one means hopping between
a markdown tearsheet, metrics.json, DataGrip and ad-hoc scripts. Analysis friction is a
research-quality problem — what is hard to inspect does not get inspected.

## Objective
`trp.lab`: the whole hypothesis->design->run->evaluate->conclude workflow behind a
handful of functions with honest defaults; a self-contained HTML report inside every run
record covering evaluation in one page; the registry mirrored into trp.duckdb so
experiments, runs and conclusions are queryable next to factor_panel in DataGrip.

## Scope
- `lab.design(...)`: hypothesis (new or by id) + experiment in one call; defaults for
  window (DEC-014 start to data edge), costs (shipped pessimistic), benchmark
  (isf-xlon-tr); everything overridable; returns the registered Experiment.
- `lab.run(experiment)`: manifest capture, backtest, metrics, tearsheet AND report.html;
  prints a headline digest; returns the run id.
- `lab.results(...)`, `lab.compare(pattern-or-ids)`, `lab.conclude(...)`,
  `lab.hypotheses()` / `lab.experiments()` listings as frames.
- `trp.reporting`: self-contained report.html per run (equity vs benchmark log curve,
  drawdown, rolling 12m Sharpe, annual excess bars, metrics + conventions tables — no
  external assets); `comparison_report([...])` overlaying several runs.
- `make db` mirrors registry tables (experiments, runs with flattened headline metrics,
  conclusions) into trp.duckdb.
- Notebook + QUERYING.md updated to lead with this workflow.

## Acceptance criteria
- [x] A new experiment on an existing hypothesis is designed, run and evaluated with <= 5
      lab calls, verified end-to-end in tests with a stub executor.
- [x] report.html renders from a real run record with zero external requests.
- [x] Registry tables appear in trp.duckdb and join against factor/backtest views.
- [x] All registry discipline (manifests, workflow, warnings) flows through unchanged —
      lab is a facade, never a bypass.

## Completion notes
- `src/trp/lab.py`: hypothesis/design/run/experiments/compare/results/conclude/report/
  open_in_browser. `design` accepts an existing `HYP-` id or a new statement+rationale
  (created a second earlier; docstring notes true pre-registration is calling
  `lab.hypothesis` before looking at anything). All calls delegate to the Registry — the
  bypass tests prove rationale-less hypotheses, unknown HYP ids and run-less conclusions
  are refused with the registry's own errors.
- `src/trp/reporting.py`: matplotlib(Agg)->inline-SVG report.html per run (header meta,
  metrics incl. relative, equity-vs-benchmark log curve + drawdown, rolling 12m Sharpe,
  annual excess bars, costs/turnover, warnings, conventions footer) and
  `comparison_report` overlaying several runs with an aligned metric table. Zero external
  requests (asserted in tests: no `http` before the first `<svg>`). matplotlib promoted
  from dev to main dependencies.
- `trp.explore._mirror_registry`: experiments + runs (flattened headline metrics) mirrored
  as DuckDB TABLES into trp.duckdb at `make db`; verified joining against factor/backtest
  views from a read-only connection.
- Dogfooded on real records: qvm-equal-current-store-r1 report.html (498 KB) and a
  three-way comparison (momentum-baseline-r3 / qvm-equal / qvm-top30) delivered.
- Docs: QUERYING.md now leads with the lab workflow ("0. The lab") and the stale
  `eodhd-gbx` source name is corrected to `eodhd-gbx2`; notebooks/explore.ipynb gained a
  lab-first cell; console `_HELP` lists fundamentals/factor_values/factor_panel.
- Tests: tests/experiments/test_lab.py (end-to-end five-call flow with stub executor,
  hypothesis reuse + variant count, bypass refusals, report smoke test on a synthetic
  run record). Full suite 850 passed.
