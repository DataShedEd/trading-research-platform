"""Automatic reproducibility manifests (QNT-064): capture everything, remember nothing.

A manifest that depends on the researcher remembering to fill it in is wrong precisely
when it matters, so capture is a function of the environment: git commit and dirty-tree
state, the version stamp of every canonical dataset a run can read, the resolved
configuration, factor definition content hashes (components included for composites),
library versions and the seed. A dirty working tree is captured as such and marks the
run non-reproducible — the registry refuses to let such a run evidence a confirmatory
conclusion (QNT-066).

``verify_reproducible`` diffs a stored manifest against a fresh capture and names every
mismatch; ``rerun`` refuses to execute across a diff rather than silently producing
different numbers.
"""

import hashlib
import json
import subprocess
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from trp.backtest.config import BacktestConfig

MANIFEST_VERSION = 1


class ManifestError(Exception):
    pass


def _git(*args: str) -> str:
    return subprocess.run(["git", *args], capture_output=True, text=True, check=True).stdout.strip()


def _digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()[:12]


def _log_tail(path: Path) -> dict[str, Any] | None:
    """The last entry of an append-only ingestion log — the dataset's version stamp."""
    if not path.exists():
        return None
    lines = [line for line in path.read_text().splitlines() if line.strip()]
    if not lines:
        return None
    entry = json.loads(lines[-1])
    return {"written_at": entry.get("written_at"), "rows_written": entry.get("rows_written")}


def _provenance(path: Path) -> dict[str, Any] | None:
    if not path.exists():
        return None
    doc = json.loads(path.read_text())
    return {"ingested_at": doc.get("ingested_at")}


def dataset_versions() -> dict[str, Any]:
    """Version stamps for every canonical dataset a research run can read.

    Big partitioned stores are identified by their append-only ingestion-log tails
    (payload immutability makes those stamps sufficient — ARCHITECTURE); small
    single-file datasets by content digest."""
    from trp.config import load_settings

    canonical = load_settings().canonical_dir
    versions: dict[str, Any] = {
        "prices": _log_tail(canonical / "prices" / "_ingestion_log.jsonl"),
        "fundamentals": _log_tail(canonical / "fundamentals" / "_ingestion_log.jsonl"),
        "benchmarks": _provenance(canonical / "benchmarks" / "isf-xlon-tr" / "provenance.json"),
        "riskfree": _provenance(canonical / "riskfree" / "uk3m-gbond" / "provenance.json"),
        "fx": _provenance(canonical / "fx" / "provenance.json"),
    }
    for name, file in (
        ("dividends", canonical / "corporate_actions" / "eodhd_ftse100_dividends_gbx.parquet"),
        ("splits", canonical / "corporate_actions" / "eodhd_ftse100_splits_gbx.parquet"),
        ("shares", canonical / "shares" / "outstanding.parquet"),
        ("membership", canonical / "universes" / "universe=FTSE100" / "membership.parquet"),
    ):
        versions[name] = _digest(file) if file.exists() else None
    return versions


def definition_hashes(config: BacktestConfig) -> dict[str, str]:
    """Content hashes of the configured factor and, for composites, every component."""
    from trp.factors.registry import FactorRegistry

    registry = FactorRegistry.load()
    definition = registry.get(config.factor, version=config.factor_version)
    hashes = {f"{definition.name}@{definition.version}": definition.content_hash}
    if definition.transform == "composite":
        from trp.factors.composite import component_specs

        for spec in component_specs(dict(definition.parameters)):
            component = registry.get(spec.name, version=spec.version)
            hashes[spec.label] = component.content_hash
    return hashes


def library_versions() -> dict[str, str]:
    import platform

    import duckdb
    import polars
    import pydantic

    return {
        "python": platform.python_version(),
        "polars": polars.__version__,
        "duckdb": duckdb.__version__,
        "pydantic": pydantic.__version__,
    }


def capture_manifest(config: BacktestConfig, *, seed: int | None = None) -> dict[str, Any]:
    dirty = bool(_git("status", "--porcelain"))
    return {
        "manifest_version": MANIFEST_VERSION,
        "captured_at": datetime.now(UTC).isoformat(),
        "git_commit": _git("rev-parse", "HEAD"),
        "working_tree_dirty": dirty,
        "config": json.loads(config.model_dump_json()),
        "config_hash": config.config_hash(),
        "seed": seed if seed is not None else config.seed,
        "definitions": definition_hashes(config),
        "datasets": dataset_versions(),
        "libraries": library_versions(),
    }


def manifest_diff(stored: dict[str, Any], fresh: dict[str, Any]) -> list[str]:
    """Every reproducibility-relevant difference, named. Empty means safe to rerun."""
    differences = []
    for key in ("git_commit", "config_hash", "seed", "definitions", "datasets", "libraries"):
        if stored.get(key) != fresh.get(key):
            differences.append(
                f"{key}: manifest has {stored.get(key)!r}, environment has {fresh.get(key)!r}"
            )
    if stored.get("working_tree_dirty"):
        differences.append("manifest was captured from a dirty working tree")
    if fresh.get("working_tree_dirty"):
        differences.append("current working tree is dirty")
    return differences


def verify_matches(stored: dict[str, Any], config: BacktestConfig) -> None:
    """Raise with the full diff unless the environment matches the stored manifest."""
    fresh = capture_manifest(config, seed=int(stored.get("seed", 0)))
    differences = manifest_diff(stored, fresh)
    if differences:
        raise ManifestError(
            "environment does not match the stored manifest:\n  - " + "\n  - ".join(differences)
        )
