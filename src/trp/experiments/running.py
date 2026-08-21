"""Run an experiment with automatic capture; re-run one with verification (QNT-064).

``run_experiment`` transitions the record, captures the manifest, executes, and stores
the run with its metrics and artefact path — no manual step anywhere. Each execution of
the same experiment gets its own immutable run (``<name>-r<n>``); nothing overwrites.

``rerun`` reconstructs the configuration from a stored manifest, verifies the current
environment matches it (commit, tree cleanliness, dataset versions, definition hashes,
libraries — the full diff on any mismatch), executes, and asserts the headline metrics
come out IDENTICAL. A reproduction that needs a tolerance is a reproduction that failed.
"""

import json
from collections.abc import Callable
from pathlib import Path
from typing import Any

from trp.backtest.config import BacktestConfig
from trp.experiments.manifest import ManifestError, capture_manifest, verify_matches
from trp.experiments.store import Registry

Executor = Callable[[BacktestConfig], tuple[dict[str, Any], str | None]]
"""config -> (headline metrics, artefact path). The real one wraps the backtest runner."""


def default_executor(config: BacktestConfig) -> tuple[dict[str, Any], str | None]:
    from trp.backtest.runner import render_tearsheet, run

    result, record, relative, rolling, directory = run(config)
    metrics: dict[str, Any] = json.loads(record.to_json())
    if relative is not None:
        metrics["relative"] = json.loads(relative.to_json())
    metrics["warnings_count"] = len(result.warnings)
    # The tearsheet lives INSIDE the immutable run record, not in tracked docs/ — an
    # executor that dirties the working tree mid-run would poison the NEXT run's
    # manifest (the registry caught exactly that on the first attempt).
    tearsheet = Path(directory) / "tearsheet.md"
    tearsheet.write_text(render_tearsheet(result, record, directory, relative, rolling))
    return metrics, str(directory)


def run_experiment(registry: Registry, experiment_id: str, executor: Executor | None = None) -> str:
    experiment = registry.start(experiment_id)
    manifest = capture_manifest(experiment.config)
    run_index = len(registry.runs_for(experiment_id)) + 1
    run_id = f"{experiment.name}-r{run_index}"
    run_config = BacktestConfig.model_validate(
        {**json.loads(experiment.config.model_dump_json()), "name": run_id}
    )
    metrics, artefact = (executor or default_executor)(run_config)
    registry.record_run(
        run_id,
        experiment_id,
        manifest=manifest,
        reproducible=not bool(manifest["working_tree_dirty"]),
        metrics=metrics,
        artefact_path=artefact,
    )
    registry.complete(experiment_id)
    return run_id


def rerun(registry: Registry, run_id: str, executor: Executor | None = None) -> dict[str, Any]:
    """Verify-and-reproduce. Returns the fresh metrics; raises on any environment diff
    or any metric that fails to reproduce exactly."""
    stored = registry.run(run_id)
    manifest: dict[str, Any] = stored["manifest"]  # type: ignore[assignment]
    config = BacktestConfig.model_validate(manifest["config"])
    verify_matches(manifest, config)
    attempt = len(registry.runs_for(str(stored["experiment_id"]))) + 1
    verify_config = BacktestConfig.model_validate(
        {**manifest["config"], "name": f"{run_id}-verify{attempt}"}
    )
    fresh_metrics, _artefact = (executor or default_executor)(verify_config)
    stored_metrics: dict[str, Any] = stored["metrics"] or {}  # type: ignore[assignment]
    mismatches = [
        f"{key}: stored {stored_metrics[key]!r} != fresh {fresh_metrics.get(key)!r}"
        for key in stored_metrics
        if stored_metrics[key] != fresh_metrics.get(key)
    ]
    if mismatches:
        raise ManifestError(
            "environment matches the manifest but the metrics do not reproduce:\n  - "
            + "\n  - ".join(mismatches)
        )
    return fresh_metrics
