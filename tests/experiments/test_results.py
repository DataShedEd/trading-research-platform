"""QNT-065: retrieval, filtered listing in stable order, missing-aware comparison."""

from datetime import date, timedelta
from pathlib import Path

import pytest

from tests.backtest.test_config import make_config
from tests.experiments.test_manifest import clean_environment, deterministic_executor  # noqa: F401
from tests.experiments.test_schema import NOW, experiment, hypothesis
from trp.backtest.config import BacktestConfig
from trp.experiments.records import ExperimentStatus
from trp.experiments.results import compare, experiment_results, list_experiments
from trp.experiments.running import run_experiment
from trp.experiments.store import Registry, RegistryError

# ruff: noqa: F811 - pytest fixtures are imported by name and reused as parameters


@pytest.fixture
def registry(tmp_path: Path) -> Registry:
    return Registry(tmp_path / "registry.sqlite")


def seeded(registry: Registry, **experiment_overrides: object):  # type: ignore[no-untyped-def]
    h = hypothesis()
    registry.add_hypothesis(h)
    e = experiment(h.hypothesis_id, **experiment_overrides)
    registry.add_experiment(e)
    return h, e


def test_everything_retrievable_together(registry: Registry, clean_environment: None) -> None:
    h, e = seeded(registry)
    run_id = run_experiment(registry, e.experiment_id, executor=deterministic_executor)
    bundle = experiment_results(registry, e.experiment_id)
    assert bundle["hypothesis"] == h
    assert bundle["experiment"].status is ExperimentStatus.COMPLETED
    assert bundle["variant_count"] == 1
    (run,) = bundle["runs"]
    assert run["run_id"] == run_id
    assert run["manifest"]["git_commit"] == "commit-abc"
    assert run["metrics"]["cagr"] == 0.109
    assert run["artefact_path"] == "/dev/null"


def test_listing_filters_and_stable_order(registry: Registry) -> None:
    h = hypothesis()
    registry.add_hypothesis(h)
    first = experiment(h.hypothesis_id, name="alpha-one", created_at=NOW)
    second = experiment(
        h.hypothesis_id,
        name="beta-two",
        created_at=NOW + timedelta(minutes=1),
        tags=("out-of-sample",),
        config=make_config(universe="FTSE250"),
        classification="exploratory",
    )
    registry.add_experiment(first)
    registry.add_experiment(second)
    assert [e.name for e in list_experiments(registry)] == ["alpha-one", "beta-two"]
    assert [e.name for e in list_experiments(registry, universe="FTSE250")] == ["beta-two"]
    assert [e.name for e in list_experiments(registry, tag="out-of-sample")] == ["beta-two"]
    assert [e.name for e in list_experiments(registry, status=ExperimentStatus.DESIGNED)] == [
        "alpha-one",
        "beta-two",
    ]
    assert list_experiments(registry, hypothesis_id="HYP-" + "0" * 36) == []


def test_listing_by_run_date(registry: Registry, clean_environment: None) -> None:
    _h, e = seeded(registry)
    run_experiment(registry, e.experiment_id, executor=deterministic_executor)
    assert [
        x.experiment_id for x in list_experiments(registry, run_on_or_after=date(2000, 1, 1))
    ] == [e.experiment_id]
    assert list_experiments(registry, run_on_or_after=date(2199, 1, 1)) == []


def test_compare_aligns_and_marks_missing_not_zero(
    registry: Registry, clean_environment: None
) -> None:
    h = hypothesis()
    registry.add_hypothesis(h)
    a = experiment(h.hypothesis_id, name="with-short-exposure")
    b = experiment(h.hypothesis_id, name="without-short-exposure")
    registry.add_experiment(a)
    registry.add_experiment(b)

    def executor_a(config: BacktestConfig):  # type: ignore[no-untyped-def]
        return {"cagr": 0.10, "short_exposure": 0.0}, None

    def executor_b(config: BacktestConfig):  # type: ignore[no-untyped-def]
        return {"cagr": 0.12}, None

    run_experiment(registry, a.experiment_id, executor=executor_a)
    run_experiment(registry, b.experiment_id, executor=executor_b)
    table = compare(registry, [a.experiment_id, b.experiment_id])
    rows = {row["metric"]: row for row in table.iter_rows(named=True)}
    assert rows["cagr"]["with-short-exposure"] == "0.1"
    assert rows["cagr"]["without-short-exposure"] == "0.12"
    # zero and never-computed must not read the same:
    assert rows["short_exposure"]["with-short-exposure"] == "0.0"
    assert rows["short_exposure"]["without-short-exposure"] is None
    with pytest.raises(RegistryError, match="at least one"):
        compare(registry, [])


def test_records_cannot_be_deleted_only_abandoned(registry: Registry) -> None:
    _h, e = seeded(registry)
    assert not hasattr(registry, "delete_experiment")
    abandoned = registry.abandon(e.experiment_id, "superseded by a cheaper design")
    assert abandoned.status is ExperimentStatus.ABANDONED
    assert registry.experiment(e.experiment_id).abandoned_reason
