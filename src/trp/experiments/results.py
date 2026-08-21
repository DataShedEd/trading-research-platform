"""Results retrieval and comparison (QNT-065).

Shapes go where they belong: scalar metrics live against the run row in the registry;
series, holdings and reports are the IMMUTABLE backtest run records under
``data/derived/backtests/<run_id>/`` that the run's ``artefact_path`` references — the
registry stores references, never the series. Re-running an experiment creates a new run
row and a new artefact directory; nothing is overwritten, nothing is deletable.

Comparison is the registry's reason to exist: ``compare`` returns metric-by-experiment
rows over an arbitrary set of experiments, aligned by metric name, with a metric absent
from some experiment marked missing (None) — a strategy whose short exposure is zero and
one where short exposure was never computed must never read the same.
"""

import json
from datetime import date
from typing import Any

import polars as pl

from trp.experiments.records import Experiment, ExperimentStatus
from trp.experiments.store import Registry, RegistryError


def experiment_results(registry: Registry, experiment_id: str) -> dict[str, Any]:
    """One experiment with everything attached: record, runs, manifests, metrics and
    artefact references, retrievable together."""
    experiment = registry.experiment(experiment_id)
    runs = [registry.run(run_id) for run_id in registry.runs_for(experiment_id)]
    return {
        "experiment": experiment,
        "hypothesis": registry.hypothesis(experiment.hypothesis_id),
        "variant_count": registry.variant_count(experiment.hypothesis_id),
        "runs": runs,
    }


def list_experiments(
    registry: Registry,
    *,
    hypothesis_id: str | None = None,
    universe: str | None = None,
    status: ExperimentStatus | None = None,
    tag: str | None = None,
    run_on_or_after: date | None = None,
) -> list[Experiment]:
    """Filtered listing in a stable, documented order: creation time, then id."""
    rows = registry._connection.execute("SELECT payload FROM experiments").fetchall()
    experiments = [Experiment.model_validate_json(payload) for (payload,) in rows]
    out = []
    for experiment in experiments:
        if hypothesis_id is not None and experiment.hypothesis_id != hypothesis_id:
            continue
        if universe is not None and experiment.config.universe != universe:
            continue
        if status is not None and experiment.status is not status:
            continue
        if tag is not None and tag not in experiment.tags:
            continue
        if run_on_or_after is not None:
            run_dates = [
                date.fromisoformat(str(registry.run(r)["started_at"])[:10])
                for r in registry.runs_for(experiment.experiment_id)
            ]
            if not any(d >= run_on_or_after for d in run_dates):
                continue
        out.append(experiment)
    return sorted(out, key=lambda e: (e.created_at, e.experiment_id))


def _scalarise(prefix: str, value: Any, into: dict[str, Any]) -> None:
    if isinstance(value, dict):
        for key, nested in value.items():
            _scalarise(f"{prefix}.{key}" if prefix else str(key), nested, into)
    elif isinstance(value, int | float | str | bool) or value is None:
        into[prefix] = value


def compare(registry: Registry, experiment_ids: list[str]) -> pl.DataFrame:
    """Aligned metrics for a set of experiments: one row per metric name, one column per
    experiment (its LATEST run's metrics); absent metrics are null, never zero."""
    if not experiment_ids:
        raise RegistryError("compare needs at least one experiment id")
    per_experiment: dict[str, dict[str, Any]] = {}
    for experiment_id in experiment_ids:
        runs = registry.runs_for(experiment_id)
        metrics: dict[str, Any] = {}
        if runs:
            raw = registry.run(runs[-1])["metrics"]
            if raw:
                _scalarise("", raw, metrics)
        per_experiment[registry.experiment(experiment_id).name] = metrics
    names = sorted({metric for metrics in per_experiment.values() for metric in metrics})
    rows = [
        {
            "metric": name,
            **{column: _rendered(metrics.get(name)) for column, metrics in per_experiment.items()},
        }
        for name in names
    ]
    return pl.DataFrame(
        rows,
        schema={"metric": pl.Utf8, **dict.fromkeys(per_experiment, pl.Utf8)},
    )


def _rendered(value: Any) -> str | None:
    if value is None:
        return None
    return json.dumps(value) if isinstance(value, bool) else str(value)
