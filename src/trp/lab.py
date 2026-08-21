"""The researcher's front door (QNT-102): five calls from idea to evaluated experiment.

    from trp import lab

    exp = lab.design(
        "qvm-ftse250-oos",
        factor="qvm_equal",
        universe="FTSE250",
        hypothesis="HYP-...",            # or a new statement string
        tags=("out-of-sample",),
    )
    run_id = lab.run(exp)                 # manifest, backtest, metrics, report.html
    lab.compare("qvm-*")                  # aligned metrics across experiments
    lab.conclude(exp, "supported", text="...", weaknesses=["..."])

This is a FACADE, never a bypass: every call goes through the registry, so hypotheses
still precede experiments, manifests still capture automatically, dirty trees still
poison confirmatory evidence, and the variant counter still bites. Defaults are the
platform's honest ones — DEC-014 window start to the data edge, shipped pessimistic
costs, the ISF total-return benchmark — and every default is overridable per call.
"""

import fnmatch
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from pathlib import Path
from typing import Any

import polars as pl

from trp.backtest.config import BacktestConfig
from trp.experiments.records import (
    Classification,
    Conclusion,
    Experiment,
    Hypothesis,
    Judgement,
    new_experiment_id,
    new_hypothesis_id,
)
from trp.experiments.results import compare as _compare
from trp.experiments.results import experiment_results, list_experiments
from trp.experiments.store import Registry, RegistryError


def _registry() -> Registry:
    from trp.config import load_settings

    return Registry(load_settings().data_dir / "registry.sqlite")


def _data_edge() -> date:
    from trp.config import load_settings

    settings = load_settings()
    return pl.read_parquet(
        settings.canonical_dir / "prices" / "*/part-*.parquet", columns=["trade_date"]
    )["trade_date"].max()  # type: ignore[return-value]


def hypothesis(statement: str, rationale: str) -> Hypothesis:
    """Write the hypothesis down FIRST — this call is why it has an earlier timestamp."""
    record = Hypothesis(
        hypothesis_id=new_hypothesis_id(),
        statement=statement,
        rationale=rationale,
        created_at=datetime.now(UTC),
    )
    _registry().add_hypothesis(record)
    return record


def design(
    name: str,
    *,
    factor: str,
    hypothesis: str,
    rationale: str | None = None,
    universe: str = "FTSE100",
    factor_version: int = 1,
    top_n: int = 20,
    start: date | None = None,
    end: date | None = None,
    classification: str = "confirmatory",
    tags: tuple[str, ...] = (),
    experiment_rationale: str | None = None,
    **config_overrides: Any,
) -> Experiment:
    """Register an experiment in one call.

    ``hypothesis`` is an existing ``HYP-...`` id, or a NEW statement when ``rationale``
    is also given (the hypothesis record is created first, seconds earlier — which keeps
    a same-call design honest, but true pre-registration is calling
    :func:`hypothesis` before you look at anything)."""
    registry = _registry()
    if hypothesis.startswith("HYP-"):
        hypothesis_id = hypothesis
        registry.hypothesis(hypothesis_id)  # must exist
    else:
        if rationale is None:
            raise RegistryError(
                "a new hypothesis statement needs its `rationale`; or pass an existing HYP- id"
            )
        record = Hypothesis(
            hypothesis_id=new_hypothesis_id(),
            statement=hypothesis,
            rationale=rationale,
            created_at=datetime.now(UTC) - timedelta(seconds=1),
        )
        registry.add_hypothesis(record)
        hypothesis_id = record.hypothesis_id

    config = BacktestConfig(
        name=name,
        start=start or date(2010, 1, 1),
        end=end or _data_edge(),
        universe=universe,
        factor=factor,
        factor_version=factor_version,
        top_n=top_n,
        initial_cash=Decimal("100000000"),
        benchmark=config_overrides.pop("benchmark", "isf-xlon-tr"),
        **config_overrides,
    )
    experiment = Experiment(
        experiment_id=new_experiment_id(),
        hypothesis_id=hypothesis_id,
        name=name,
        rationale=experiment_rationale or f"{factor} v{factor_version} on {universe}",
        config=config,
        classification=Classification(classification),
        tags=tags,
        created_at=datetime.now(UTC),
    )
    registry.add_experiment(experiment)
    return experiment


def run(experiment: Experiment | str, *, report: bool = True) -> str:
    """Execute with full capture; write report.html into the run record; print a digest."""
    from trp.experiments.running import run_experiment

    registry = _registry()
    experiment_id = experiment if isinstance(experiment, str) else experiment.experiment_id
    run_id = run_experiment(registry, experiment_id)
    row = registry.run(run_id)
    if report and row["artefact_path"]:
        from trp.reporting import run_report

        path = run_report(Path(str(row["artefact_path"])))
        print(f"report: {path}")
    metrics: dict[str, Any] = row["metrics"] or {}  # type: ignore[assignment]
    digest: dict[str, Any] = {
        key: metrics.get(key) for key in ("cagr", "sharpe", "max_drawdown") if key in metrics
    }
    relative = metrics.get("relative") or {}
    if relative:
        digest["information_ratio"] = relative.get("information_ratio")
    rendered = ", ".join(f"{key} {value:.3f}" for key, value in digest.items() if value is not None)
    print(f"{run_id}: {rendered}  (reproducible: {row['reproducible']})")
    return run_id


def experiments(pattern: str = "*") -> pl.DataFrame:
    """Every experiment matching the name pattern, as a frame."""
    rows = []
    for record in list_experiments(_registry()):
        if not fnmatch.fnmatch(record.name, pattern):
            continue
        rows.append(
            {
                "name": record.name,
                "experiment_id": record.experiment_id,
                "hypothesis_id": record.hypothesis_id,
                "status": record.status.value,
                "classification": record.classification.value,
                "universe": record.config.universe,
                "factor": f"{record.config.factor}@{record.config.factor_version}",
                "top_n": record.config.top_n,
                "tags": ",".join(record.tags),
                "created_at": record.created_at,
            }
        )
    return pl.DataFrame(rows)


def _resolve_ids(selection: str | list[str]) -> list[str]:
    if isinstance(selection, list):
        return selection
    frame = experiments(selection)
    if frame.is_empty():
        raise RegistryError(f"no experiments match {selection!r}")
    return frame["experiment_id"].to_list()


def compare(selection: str | list[str]) -> pl.DataFrame:
    """Aligned metrics across experiments — a name pattern ('qvm-*') or explicit ids."""
    return _compare(_registry(), _resolve_ids(selection))


def results(name_or_id: str) -> dict[str, Any]:
    """The full bundle: record, hypothesis, variant count, runs with manifests/metrics."""
    registry = _registry()
    if name_or_id.startswith("EXP-"):
        return experiment_results(registry, name_or_id)
    frame = experiments(name_or_id)
    if frame.height != 1:
        raise RegistryError(f"{name_or_id!r} matches {frame.height} experiments; be exact")
    return experiment_results(registry, frame["experiment_id"][0])


def conclude(
    experiment: Experiment | str,
    judgement: str,
    *,
    text: str,
    weaknesses: list[str],
    evidence_run: str | None = None,
    follow_ups: list[str] | None = None,
    parameter_sensitivity: str | None = None,
) -> Experiment:
    """Conclude with the registry's full discipline (evidence citation, weaknesses,
    variant counting and the multiple-testing warning all apply)."""
    registry = _registry()
    experiment_id = experiment if isinstance(experiment, str) else experiment.experiment_id
    if evidence_run is None:
        runs = registry.runs_for(experiment_id)
        if not runs:
            raise RegistryError("no runs to cite; run the experiment first")
        evidence_run = runs[-1]
    concluded = registry.conclude(
        experiment_id,
        Conclusion(
            judgement=Judgement(judgement),
            text=text,
            evidence_run_id=evidence_run,
            weaknesses=tuple(weaknesses),
            follow_ups=tuple(follow_ups or ()),
            parameter_sensitivity=parameter_sensitivity,
            concluded_at=datetime.now(UTC),
        ),
    )
    warning = concluded.conclusion.multiple_testing_warning if concluded.conclusion else None
    if warning:
        print(f"MULTIPLE-TESTING WARNING: {warning}")
    return concluded


def report(selection: str | list[str]) -> Path:
    """A comparison report across experiments' latest runs (single page, no hopping)."""
    from trp.reporting import comparison_report

    registry = _registry()
    run_dirs = []
    for experiment_id in _resolve_ids(selection):
        runs = registry.runs_for(experiment_id)
        if runs:
            artefact = registry.run(runs[-1])["artefact_path"]
            if artefact:
                run_dirs.append(Path(str(artefact)))
    if not run_dirs:
        raise RegistryError("no runs with artefacts in the selection")
    return comparison_report(run_dirs)


def open_in_browser(path: Path) -> None:
    import webbrowser

    webbrowser.open(path.resolve().as_uri())
