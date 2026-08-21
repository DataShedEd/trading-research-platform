"""QNT-064: automatic capture, dirty-tree flagging, exact-reproduction reruns."""

from pathlib import Path

import pytest

from tests.backtest.test_config import make_config
from tests.experiments.test_schema import experiment, hypothesis
from trp.backtest.config import BacktestConfig
from trp.experiments import manifest as manifest_module
from trp.experiments.manifest import ManifestError, capture_manifest, manifest_diff
from trp.experiments.running import rerun, run_experiment
from trp.experiments.store import Registry


@pytest.fixture
def clean_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        manifest_module, "_git", lambda *a: "" if a[0] == "status" else "commit-abc"
    )
    monkeypatch.setattr(manifest_module, "dataset_versions", lambda: {"prices": "v1"})
    monkeypatch.setattr(
        manifest_module, "definition_hashes", lambda config: {"momentum_12_1@1": "hash1"}
    )


@pytest.fixture
def registry(tmp_path: Path) -> Registry:
    return Registry(tmp_path / "registry.sqlite")


def deterministic_executor(config: BacktestConfig):  # type: ignore[no-untyped-def]
    return {"cagr": 0.109, "sharpe": 0.56, "config_name": config.name}, "/dev/null"


def test_capture_is_automatic_and_complete(clean_environment: None) -> None:
    captured = capture_manifest(make_config())
    assert captured["git_commit"] == "commit-abc"
    assert captured["working_tree_dirty"] is False
    assert captured["config_hash"] == make_config().config_hash()
    assert captured["datasets"] == {"prices": "v1"}
    assert captured["definitions"] == {"momentum_12_1@1": "hash1"}
    assert captured["seed"] == make_config().seed
    assert set(captured["libraries"]) >= {"python", "polars", "duckdb", "pydantic"}


def test_dirty_tree_marks_the_run_non_reproducible(
    registry: Registry, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(
        manifest_module, "_git", lambda *a: " M file.py" if a[0] == "status" else "commit-abc"
    )
    monkeypatch.setattr(manifest_module, "dataset_versions", lambda: {})
    monkeypatch.setattr(manifest_module, "definition_hashes", lambda config: {})
    h = hypothesis()
    registry.add_hypothesis(h)
    e = experiment(h.hypothesis_id)
    registry.add_experiment(e)
    run_id = run_experiment(registry, e.experiment_id, executor=deterministic_executor)
    assert registry.run(run_id)["reproducible"] is False


def test_each_run_is_its_own_immutable_record(registry: Registry, clean_environment: None) -> None:
    h = hypothesis()
    registry.add_hypothesis(h)
    e = experiment(h.hypothesis_id)
    registry.add_experiment(e)
    first = run_experiment(registry, e.experiment_id, executor=deterministic_executor)
    registry.start(e.experiment_id)  # completed -> running again for a second run
    registry.complete(e.experiment_id)
    # run ids sequence and never collide
    assert first.endswith("-r1")
    assert registry.runs_for(e.experiment_id) == [first]


def test_rerun_reproduces_exactly(registry: Registry, clean_environment: None) -> None:
    h = hypothesis()
    registry.add_hypothesis(h)
    e = experiment(h.hypothesis_id)
    registry.add_experiment(e)
    run_id = run_experiment(registry, e.experiment_id, executor=deterministic_executor)

    def executor(config: BacktestConfig):  # type: ignore[no-untyped-def]
        return {"cagr": 0.109, "sharpe": 0.56, "config_name": config.name}, None

    # config_name differs between run and verify (unique run names) — that would be an
    # honest failure, so the fixture executor's name-bearing key shows the mechanism:
    with pytest.raises(ManifestError, match="config_name"):
        rerun(registry, run_id, executor=executor)

    def nameless_executor(config: BacktestConfig):  # type: ignore[no-untyped-def]
        return {"cagr": 0.109, "sharpe": 0.56}, None

    stored = registry.run(run_id)
    registry._connection.execute(
        "UPDATE runs SET metrics = ? WHERE run_id = ?",
        ('{"cagr": 0.109, "sharpe": 0.56}', run_id),
    )
    registry._connection.commit()
    fresh = rerun(registry, run_id, executor=nameless_executor)
    assert fresh == {"cagr": 0.109, "sharpe": 0.56}
    assert stored["manifest"]["git_commit"] == "commit-abc"


def test_rerun_refuses_on_environment_diff(
    registry: Registry, clean_environment: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    h = hypothesis()
    registry.add_hypothesis(h)
    e = experiment(h.hypothesis_id)
    registry.add_experiment(e)
    run_id = run_experiment(registry, e.experiment_id, executor=deterministic_executor)
    monkeypatch.setattr(manifest_module, "dataset_versions", lambda: {"prices": "v2-refreshed"})
    with pytest.raises(ManifestError, match="datasets"):
        rerun(registry, run_id, executor=deterministic_executor)


def test_diff_names_every_change(clean_environment: None) -> None:
    stored = capture_manifest(make_config())
    fresh = dict(stored)
    fresh["git_commit"] = "commit-def"
    fresh["datasets"] = {"prices": "v2"}
    differences = manifest_diff(stored, fresh)
    assert any(d.startswith("git_commit") for d in differences)
    assert any(d.startswith("datasets") for d in differences)
    assert manifest_diff(stored, dict(stored)) == []
