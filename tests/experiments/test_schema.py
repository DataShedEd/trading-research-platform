"""QNT-063: registry schema — required fields, round-trips, loud version failures."""

import json
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path

import pytest
from pydantic import ValidationError

from tests.backtest.test_config import make_config
from trp.experiments.records import (
    Classification,
    Conclusion,
    Experiment,
    ExperimentStatus,
    Hypothesis,
    Judgement,
    new_experiment_id,
    new_hypothesis_id,
)
from trp.experiments.store import Registry, RegistryError

NOW = datetime(2026, 8, 21, 12, 0, tzinfo=UTC)


def hypothesis(**overrides: object) -> Hypothesis:
    values: dict[str, object] = {
        "hypothesis_id": new_hypothesis_id(),
        "statement": "FTSE 100 momentum with quality tilt beats momentum alone net of costs",
        "rationale": "premia are weakly correlated",
        "created_at": NOW - timedelta(days=1),
    }
    values.update(overrides)
    return Hypothesis.model_validate(values)


def experiment(hypothesis_id: str, **overrides: object) -> Experiment:
    values: dict[str, object] = {
        "experiment_id": new_experiment_id(),
        "hypothesis_id": hypothesis_id,
        "name": "qvm-vs-momentum-v1",
        "rationale": "the pre-registered equal-thirds blend",
        "config": make_config(),
        "classification": Classification.CONFIRMATORY,
        "created_at": NOW,
    }
    values.update(overrides)
    return Experiment.model_validate(values)


def conclusion(run_id: str = "run-1", **overrides: object) -> Conclusion:
    values: dict[str, object] = {
        "judgement": Judgement.SUPPORTED,
        "text": "excess CAGR positive and robust to the documented perturbations",
        "evidence_run_id": run_id,
        "weaknesses": ("single universe", "DEC-007 imputed availability"),
        "concluded_at": NOW + timedelta(days=2),
    }
    values.update(overrides)
    return Conclusion.model_validate(values)


@pytest.fixture
def registry(tmp_path: Path) -> Registry:
    return Registry(tmp_path / "registry.sqlite")


def test_required_fields_are_structural() -> None:
    with pytest.raises(ValidationError):  # a vague hypothesis is not a hypothesis
        hypothesis(statement="momentum works")
    with pytest.raises(ValidationError):  # no naive timestamps
        hypothesis(created_at=datetime(2026, 1, 1))  # noqa: DTZ001
    with pytest.raises(ValidationError):  # config carries universe/costs/benchmark: required
        Experiment.model_validate(
            {
                "experiment_id": new_experiment_id(),
                "hypothesis_id": new_hypothesis_id(),
                "name": "x",
                "rationale": "r",
                "classification": "confirmatory",
                "created_at": NOW,
            }
        )


def test_conclusion_requires_weaknesses() -> None:
    with pytest.raises(ValidationError):
        conclusion(weaknesses=())


def test_status_shape_invariants() -> None:
    h = hypothesis()
    with pytest.raises(ValidationError, match="imply each other"):
        experiment(h.hypothesis_id, status=ExperimentStatus.CONCLUDED)
    with pytest.raises(ValidationError, match="reason"):
        experiment(h.hypothesis_id, status=ExperimentStatus.ABANDONED)
    with pytest.raises(ValidationError, match="started_at"):
        experiment(h.hypothesis_id, status=ExperimentStatus.RUNNING)


def test_round_trip_returns_an_equal_object(registry: Registry) -> None:
    h = hypothesis()
    registry.add_hypothesis(h)
    assert registry.hypothesis(h.hypothesis_id) == h
    e = experiment(h.hypothesis_id, config=make_config(initial_cash=Decimal("123456")))
    registry.add_experiment(e)
    assert registry.experiment(e.experiment_id) == e


def test_unknown_fields_from_the_future_fail_loudly(registry: Registry) -> None:
    h = hypothesis()
    registry.add_hypothesis(h)
    # simulate a future writer adding a field this code does not know
    doctored = json.loads(h.model_dump_json())
    doctored["novel_field"] = "surprise"
    registry._connection.execute(
        "UPDATE hypotheses SET payload = ? WHERE hypothesis_id = ?",
        (json.dumps(doctored), h.hypothesis_id),
    )
    with pytest.raises(RegistryError, match="newer schema"):
        registry.hypothesis(h.hypothesis_id)


def test_schema_version_mismatch_refuses_to_open(tmp_path: Path) -> None:
    path = tmp_path / "registry.sqlite"
    Registry(path)
    import sqlite3

    connection = sqlite3.connect(path)
    connection.execute("PRAGMA user_version = 99")
    connection.commit()
    connection.close()
    with pytest.raises(RegistryError, match="migrate deliberately"):
        Registry(path)


def test_experiment_requires_an_existing_hypothesis(registry: Registry) -> None:
    with pytest.raises(RegistryError, match="no hypothesis"):
        registry.add_experiment(experiment(new_hypothesis_id()))
