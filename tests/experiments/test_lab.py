"""QNT-102: the lab facade — five calls, full discipline underneath."""

from pathlib import Path

import pytest

from tests.experiments.test_manifest import clean_environment  # noqa: F401
from trp.experiments.records import ExperimentStatus
from trp.experiments.store import Registry, RegistryError

# ruff: noqa: F811 - pytest fixtures are imported by name and reused as parameters


@pytest.fixture
def lab(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):  # type: ignore[no-untyped-def]
    """The lab pointed at a scratch registry and a stubbed executor + data edge."""
    from trp import lab as lab_module

    registry = Registry(tmp_path / "registry.sqlite")
    monkeypatch.setattr(lab_module, "_registry", lambda: registry)
    from datetime import date

    monkeypatch.setattr(lab_module, "_data_edge", lambda: date(2026, 1, 1))

    import trp.experiments.running as running_module

    def stub_executor(config):  # type: ignore[no-untyped-def]
        return {
            "cagr": 0.11,
            "sharpe": 0.6,
            "max_drawdown": -0.4,
            "relative": {"information_ratio": 0.35},
        }, None

    monkeypatch.setattr(running_module, "default_executor", stub_executor)
    return lab_module


def test_five_calls_from_idea_to_conclusion(lab, clean_environment) -> None:  # type: ignore[no-untyped-def]
    exp = lab.design(
        "qvm-oos-check",
        factor="qvm_equal",
        hypothesis="QVM survives out-of-sample on a fresh universe and period basis",
        rationale="the in-sample IR advantage needs an untouched test set",
        universe="FTSE250",
        tags=("out-of-sample",),
        classification="confirmatory",
    )
    run_id = lab.run(exp, report=False)
    assert run_id == "qvm-oos-check-r1"

    frame = lab.experiments("qvm-*")
    assert frame["status"].to_list() == ["completed"]
    assert frame["universe"].to_list() == ["FTSE250"]

    table = lab.compare("qvm-*")
    assert "qvm-oos-check" in table.columns

    concluded = lab.conclude(
        exp,
        "supported",
        text="stub-run evidence flows through the registry discipline end to end",
        weaknesses=["a stub executor is not a market"],
    )
    assert concluded.status is ExperimentStatus.CONCLUDED
    assert concluded.conclusion.evidence_run_id == run_id  # auto-cited latest run


def test_design_reuses_an_existing_hypothesis(lab, clean_environment) -> None:  # type: ignore[no-untyped-def]
    written_first = lab.hypothesis(
        "written before anything ran, as the discipline demands", "pre-registration"
    )
    exp = lab.design(
        "variant-one",
        factor="momentum_12_1",
        hypothesis=written_first.hypothesis_id,
    )
    assert exp.hypothesis_id == written_first.hypothesis_id
    second = lab.design(
        "variant-two", factor="momentum_6_1", hypothesis=written_first.hypothesis_id
    )
    assert lab.results("variant-two")["variant_count"] == 2
    assert second.config.benchmark == "isf-xlon-tr"  # the honest defaults applied


def test_lab_cannot_bypass_the_registry(lab, clean_environment) -> None:  # type: ignore[no-untyped-def]
    with pytest.raises(RegistryError, match="rationale"):
        lab.design("orphan", factor="roe", hypothesis="a new statement with no rationale here")
    with pytest.raises(RegistryError, match="no hypothesis"):
        lab.design("orphan", factor="roe", hypothesis="HYP-" + "0" * 36)
    exp = lab.design(
        "unrun",
        factor="roe",
        hypothesis="conclusions cannot be drawn before any run exists at all",
        rationale="r",
    )
    with pytest.raises(RegistryError, match="run the experiment first"):
        lab.conclude(exp, "supported", text="premature conclusion attempt", weaknesses=["x"])


def test_report_renders_from_a_real_shaped_record(tmp_path: Path) -> None:
    """The HTML report renders self-contained from run-record artefacts alone."""
    import json
    from datetime import date, timedelta

    import polars as pl

    from trp.reporting import run_report

    run_dir = tmp_path / "toy-run"
    run_dir.mkdir()
    days = [date(2021, 1, 4) + timedelta(days=i) for i in range(40)]
    values = [1_000_000 * (1 + 0.001) ** i for i in range(40)]
    pl.DataFrame(
        {"date": days, "value": values, "cash": [0.0] * 40, "positions": [10] * 40}
    ).write_parquet(run_dir / "daily.parquet")
    pl.DataFrame(
        {
            "date": days[:2],
            "trades": [10, 2],
            "traded_value": [1e6, 1e5],
            "turnover": [0.5, 0.05],
            "costs": [500.0, 50.0],
        }
    ).write_parquet(run_dir / "rebalances.parquet")
    (run_dir / "config.json").write_text(
        json.dumps(
            {
                "factor": "toy",
                "factor_version": 1,
                "universe": "TEST",
                "start": "2021-01-04",
                "end": "2021-02-12",
                "top_n": 10,
            }
        )
    )
    (run_dir / "meta.json").write_text(
        json.dumps({"config_hash": "abc", "git_commit": "def", "warnings": []})
    )
    (run_dir / "metrics.json").write_text(
        json.dumps({"cagr": 0.28, "sharpe": 2.0, "max_drawdown": -0.01, "flags": []})
    )
    report = run_report(run_dir)
    html = report.read_text()
    assert "<svg" in html and "http" not in html.split("<svg")[0]  # no external assets
    assert "toy-run" in html and "Sharpe" in html
