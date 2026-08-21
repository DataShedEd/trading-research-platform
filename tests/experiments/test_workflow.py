"""QNT-066: the four-artefact workflow, enforced — sequence, counting, warnings."""

from datetime import timedelta
from pathlib import Path

import pytest
from pydantic import ValidationError

from tests.experiments.test_manifest import clean_environment, deterministic_executor  # noqa: F401
from tests.experiments.test_schema import NOW, conclusion, experiment, hypothesis
from trp.experiments.records import (
    ALLOWED_TRANSITIONS,
    Classification,
    ExperimentStatus,
)
from trp.experiments.running import run_experiment
from trp.experiments.store import Registry, RegistryError

# ruff: noqa: F811 - pytest fixtures are imported by name and reused as parameters


@pytest.fixture
def registry(tmp_path: Path) -> Registry:
    return Registry(tmp_path / "registry.sqlite")


def completed_with_run(registry: Registry, **overrides: object) -> tuple:  # type: ignore[type-arg]
    h = hypothesis()
    registry.add_hypothesis(h)
    e = experiment(h.hypothesis_id, **overrides)
    registry.add_experiment(e)
    run_id = run_experiment(registry, e.experiment_id, executor=deterministic_executor)
    return h, e, run_id


def test_no_experiment_without_a_prior_hypothesis(registry: Registry) -> None:
    h = hypothesis(created_at=NOW + timedelta(hours=1))  # written AFTER the experiment
    registry.add_hypothesis(h)
    with pytest.raises(RegistryError, match="exploratory by definition"):
        registry.add_experiment(
            experiment(h.hypothesis_id, classification=Classification.CONFIRMATORY)
        )
    # ...but the same record IS admissible as exploratory.
    registry.add_experiment(experiment(h.hypothesis_id, classification=Classification.EXPLORATORY))


def test_every_illegal_transition_is_rejected(registry: Registry, clean_environment: None) -> None:
    statuses = list(ExperimentStatus)
    for source in statuses:
        for target in statuses:
            if target in ALLOWED_TRANSITIONS[source] or target is source:
                continue
            h = hypothesis()
            registry.add_hypothesis(h)
            e = experiment(h.hypothesis_id)
            registry.add_experiment(e)
            # walk the experiment to `source` legally
            if source in (ExperimentStatus.RUNNING, ExperimentStatus.COMPLETED):
                registry.start(e.experiment_id)
            if source is ExperimentStatus.COMPLETED:
                registry.complete(e.experiment_id)
            if source is ExperimentStatus.ABANDONED:
                registry.abandon(e.experiment_id, "walked here for the test")
            if source is ExperimentStatus.CONCLUDED:
                run_id = f"seed-run-{e.experiment_id}"
                registry.record_run(run_id, e.experiment_id, manifest={}, reproducible=True)
                registry.start(e.experiment_id)
                registry.complete(e.experiment_id)
                registry.conclude(e.experiment_id, conclusion(run_id))
            mover = {
                ExperimentStatus.DESIGNED: None,  # no transition returns to designed
                ExperimentStatus.RUNNING: lambda x=e: registry.start(x.experiment_id),
                ExperimentStatus.COMPLETED: lambda x=e: registry.complete(x.experiment_id),
                ExperimentStatus.CONCLUDED: lambda x=e: registry.conclude(
                    x.experiment_id, conclusion("nonexistent-run")
                ),
                ExperimentStatus.ABANDONED: lambda x=e: registry.abandon(x.experiment_id, "reason"),
            }[target]
            if mover is None:
                continue
            # rejection may come from the store's transition rule or, equivalently,
            # from the record's own shape invariants — both are the system saying no
            with pytest.raises((RegistryError, ValidationError)):
                mover()


def test_variant_count_includes_abandoned(registry: Registry) -> None:
    h = hypothesis()
    registry.add_hypothesis(h)
    for index in range(3):
        e = experiment(h.hypothesis_id, name=f"variant-{index}")
        registry.add_experiment(e)
        if index == 0:
            registry.abandon(e.experiment_id, "dead end, kept as the denominator")
    assert registry.variant_count(h.hypothesis_id) == 3


def test_conclusion_requires_a_real_run_of_this_experiment(
    registry: Registry, clean_environment: None
) -> None:
    _h, e, run_id = completed_with_run(registry)
    with pytest.raises(RegistryError, match="not on record"):
        registry.conclude(e.experiment_id, conclusion("made-up-run"))
    # a run belonging to a different experiment is not this experiment's evidence
    h2 = hypothesis()
    registry.add_hypothesis(h2)
    other = experiment(h2.hypothesis_id, name="other-experiment")
    registry.add_experiment(other)
    other_run = run_experiment(registry, other.experiment_id, executor=deterministic_executor)
    with pytest.raises(RegistryError, match="different experiment"):
        registry.conclude(e.experiment_id, conclusion(other_run))
    concluded = registry.conclude(e.experiment_id, conclusion(run_id))
    assert concluded.conclusion is not None
    assert concluded.conclusion.multiple_testing_warning is None  # one variant only


def test_dirty_run_cannot_evidence_a_confirmatory_conclusion(
    registry: Registry, monkeypatch: pytest.MonkeyPatch
) -> None:
    from trp.experiments import manifest as manifest_module

    monkeypatch.setattr(
        manifest_module, "_git", lambda *a: " M x.py" if a[0] == "status" else "commit-abc"
    )
    monkeypatch.setattr(manifest_module, "dataset_versions", lambda: {})
    monkeypatch.setattr(manifest_module, "definition_hashes", lambda config: {})
    _h, e, run_id = completed_with_run(registry)
    with pytest.raises(RegistryError, match="dirty working tree"):
        registry.conclude(e.experiment_id, conclusion(run_id))


def test_multiple_testing_warning_and_its_only_clearance(
    registry: Registry, clean_environment: None
) -> None:
    h = hypothesis()
    registry.add_hypothesis(h)
    experiments = []
    for index in range(6):  # over the documented threshold of 5
        e = experiment(h.hypothesis_id, name=f"variant-{index}")
        registry.add_experiment(e)
        experiments.append(e)
    run_id = run_experiment(
        registry, experiments[-1].experiment_id, executor=deterministic_executor
    )
    concluded = registry.conclude(experiments[-1].experiment_id, conclusion(run_id))
    warning = concluded.conclusion.multiple_testing_warning
    assert warning is not None and "6 variants" in warning and "out-of-sample" in warning

    # the ONLY clearance: an out-of-sample run on record for the hypothesis
    oos = experiment(h.hypothesis_id, name="holdout", tags=("out-of-sample",))
    registry.add_experiment(oos)
    oos_run = run_experiment(registry, oos.experiment_id, executor=deterministic_executor)
    cleared = registry.conclude(oos.experiment_id, conclusion(oos_run))
    assert cleared.conclusion.multiple_testing_warning is None
