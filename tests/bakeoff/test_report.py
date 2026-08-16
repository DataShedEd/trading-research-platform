"""QNT-036: the generated Results section, over synthetic runs and one end-to-end run.

The real `docs/DATA_PROVIDER_EVALUATION.md` is never written by these tests — no real run
exists yet, and a plausible-looking table of scores for a provider nobody has called is the
one artefact this repository must not produce by accident. Document round-trips work on a
copy in `tmp_path`.
"""

import json
from datetime import UTC, date, datetime
from decimal import Decimal
from pathlib import Path
from typing import Any

import pytest

from tests.fakes.provider import FakeProvider, NoFundamentalsProvider
from trp.bakeoff.checks import CheckResult, Criterion, Outcome
from trp.bakeoff.checks_corporate_actions import CORPORATE_ACTION_CHECKS
from trp.bakeoff.checks_pit_fundamentals import PIT_FUNDAMENTAL_CHECKS
from trp.bakeoff.harness import RunConfig, run_bakeoff
from trp.bakeoff.report import (
    GENERATED_BEGIN,
    GENERATED_END,
    RESULTS_HEADING,
    ReportError,
    main,
    render_report,
    update_results_section,
)
from trp.bakeoff.results import CellRecord, FetchStatus, RunMetadata, load_run
from trp.bakeoff.scoring import DeclaredScore, score_provider
from trp.bakeoff.universe.loader import Market, load_universe
from trp.providers.base import Dataset, RawPayload

NOW = datetime(2026, 8, 16, 9, 30, tzinfo=UTC)
DOC = Path(__file__).resolve().parents[2] / "docs" / "DATA_PROVIDER_EVALUATION.md"

DECLARED_CRITERIA = (Criterion.RATE_LIMITS_BULK, Criterion.LICENSING, Criterion.COST)
EMPIRICAL_CRITERIA = tuple(c for c in Criterion if c not in DECLARED_CRITERIA)


def metadata(providers: dict[str, str] | None = None) -> RunMetadata:
    return RunMetadata(
        run_id="synthetic-run",
        universe_version="2026-08-16.1",
        providers=providers or {"alpha": "1.0", "beta": "2.0"},
        started_at=NOW,
        filters={"datasets": ["prices"], "markets": [], "properties": []},
    )


def result(
    criterion: Criterion,
    outcome: Outcome,
    provider: str,
    *,
    check: str = "chk",
    security: str = "apple",
    explanation: str = "synthetic",
) -> CheckResult:
    return CheckResult(
        check=check,
        criterion=criterion,
        provider=provider,
        security_key=security,
        dataset=Dataset.PRICES,
        outcome=outcome,
        expected="expected value",
        observed="observed value",
        explanation=explanation,
        raw_refs=("data/raw/alpha/prices/abc/payload.json",),
    )


def cell(
    checks: list[CheckResult],
    provider: str,
    dataset: Dataset = Dataset.PRICES,
    status: FetchStatus = FetchStatus.OK,
) -> CellRecord:
    return CellRecord(
        provider=provider,
        security_key="apple",
        dataset=dataset,
        fetch_status=status,
        checks=tuple(checks),
        completed_at=NOW,
    )


def declared(provider: str) -> list[DeclaredScore]:
    return [
        DeclaredScore(
            provider=provider,
            criterion=criterion,
            score=Decimal(1),
            reason=f"{criterion.value} researched (QNT-028): EUR 99.99/month (~GBP 85)",
        )
        for criterion in DECLARED_CRITERIA
    ]


def perfect(provider: str, failures: dict[Criterion, Outcome] | None = None) -> list[CellRecord]:
    outcomes = failures or {}
    return [
        cell(
            [
                result(criterion, outcomes.get(criterion, Outcome.PASS), provider)
                for criterion in EMPIRICAL_CRITERIA
            ],
            provider,
        )
    ]


def render(
    cells: list[CellRecord],
    providers: list[str],
    *,
    provisional: bool = True,
    **kwargs: Any,
) -> str:
    scores = [score_provider(name, cells, declared(name)) for name in providers]
    return render_report(
        metadata(dict.fromkeys(providers, "1.0")),
        cells,
        scores,
        generated_at=NOW,
        declared=[d for name in providers for d in declared(name)],
        provisional=provisional,
        provisional_reason="Rendered by the QNT-036 test suite.",
        **kwargs,
    )


# ------------------------------------------------------------------ document region


def doc_copy(tmp_path: Path) -> Path:
    """A copy of the real evaluation doc — the real one is never touched by tests."""
    copy = tmp_path / "DATA_PROVIDER_EVALUATION.md"
    copy.write_text(DOC.read_text())
    return copy


def test_hand_written_content_above_the_region_survives_byte_for_byte(tmp_path: Path) -> None:
    path = doc_copy(tmp_path)
    original = path.read_text()
    preamble = original[: original.index(RESULTS_HEADING)]

    update_results_section(path, render(perfect("alpha"), ["alpha"]))

    updated = path.read_text()
    assert updated.startswith(preamble)
    assert GENERATED_BEGIN in updated and GENERATED_END in updated
    assert "OWNER DECISION GATE" in updated  # the hand-written gate note is still there


def test_hand_written_content_below_the_region_survives_regeneration(tmp_path: Path) -> None:
    path = doc_copy(tmp_path)
    update_results_section(path, render(perfect("alpha"), ["alpha"]))
    trailer = "\n## Appendix (hand-written)\n\nNotes that must survive regeneration.\n"
    path.write_text(path.read_text() + trailer)

    update_results_section(
        path, render(perfect("alpha", {Criterion.HISTORICAL_DEPTH: Outcome.FAIL}), ["alpha"])
    )

    updated = path.read_text()
    assert updated.endswith(trailer)
    assert updated.count(GENERATED_BEGIN) == 1
    assert updated.count(GENERATED_END) == 1


def test_regeneration_is_idempotent_byte_for_byte(tmp_path: Path) -> None:
    path = doc_copy(tmp_path)
    rendered = render(perfect("alpha"), ["alpha"])
    update_results_section(path, rendered)
    once = path.read_bytes()
    update_results_section(path, rendered)
    assert path.read_bytes() == once


def test_a_document_without_a_results_heading_is_refused(tmp_path: Path) -> None:
    path = tmp_path / "other.md"
    path.write_text("# Something else\n")
    with pytest.raises(ReportError, match="no '## Results' heading"):
        update_results_section(path, render(perfect("alpha"), ["alpha"]))


# ------------------------------------------------------------------------ contents


def test_provisional_banner_cannot_be_mistaken_for_a_real_evaluation() -> None:
    rendered = render(perfect("alpha"), ["alpha"])
    assert "PROVISIONAL — GENERATED FROM FAKE/TEST DATA" in rendered
    assert "must not inform a purchase" in rendered
    assert "Rendered by the QNT-036 test suite." in rendered


def test_a_real_render_carries_no_provisional_banner() -> None:
    rendered = render(perfect("alpha"), ["alpha"], provisional=False)
    assert "PROVISIONAL" not in rendered
    assert "This section is generated" in rendered


def test_provenance_block_is_complete() -> None:
    rendered = render(
        perfect("alpha"),
        ["alpha"],
        git_commit="0123456789abcdef",
        tiers={"alpha": "ALL-IN-ONE"},
        declared_verified_on=date(2026, 8, 16),
    )
    for field in (
        "Run identifier",
        "Run started",
        "Report generated",
        "Validation universe version",
        "Weight-file version",
        "Adapter versions",
        "Git commit",
        "Tier tested",
        "Declared inputs verified",
    ):
        assert f"| {field} |" in rendered
    assert "`synthetic-run`" in rendered
    assert "`2026-08-16T09:30:00Z`" in rendered  # UTC with an explicit Z
    assert "`2026-08-16.1`" in rendered
    assert "0123456789abcdef" in rendered
    assert "ALL-IN-ONE" in rendered


def test_scores_render_at_a_fixed_precision() -> None:
    rendered = render(perfect("alpha"), ["alpha"])
    assert "| 1.000 |" in rendered


def test_unmeasured_criteria_show_as_unmeasured_not_zero() -> None:
    cells = [cell([result(Criterion.HISTORICAL_DEPTH, Outcome.PASS, "alpha")], "alpha")]
    rendered = render(cells, ["alpha"])
    assert "unmeasured" in rendered
    assert "no applicable check results" in rendered
    assert "excluded from the total; remaining weights renormalised" in rendered


def test_capability_zero_is_distinguished_from_unmeasured() -> None:
    cells = [
        cell([result(Criterion.HISTORICAL_DEPTH, Outcome.PASS, "alpha")], "alpha"),
        cell([], "alpha", dataset=Dataset.FUNDAMENTALS, status=FetchStatus.UNSUPPORTED),
    ]
    rendered = render(cells, ["alpha"])
    assert "dataset(s) not offered by provider/tier: fundamentals" in rendered
    assert "capability gap, scored zero" in rendered
    assert "UNSUITABLE — veto criterion failed" in rendered  # pit_fundamentals veto


def test_veto_failure_leads_the_provider_section() -> None:
    cells = perfect("alpha", {Criterion.DELISTED_COVERAGE: Outcome.FAIL})
    rendered = render(cells, ["alpha"])
    section = rendered[rendered.index("### alpha") :]
    veto_line = section.index("UNSUITABLE — veto criterion failed")
    table_line = section.index("| Criterion | Weight |")
    assert veto_line < table_line
    assert "DEC-012" in section


def test_failed_examples_are_selected_deterministically_heaviest_first() -> None:
    cells = [
        cell(
            [
                result(Criterion.API_RELIABILITY, Outcome.FAIL, "alpha", check="light"),
                result(Criterion.DELISTED_COVERAGE, Outcome.FAIL, "alpha", check="heavy"),
                result(Criterion.CORPORATE_ACTION_ACCURACY, Outcome.FAIL, "alpha", check="middle"),
            ],
            "alpha",
        )
    ]
    rendered = render(cells, ["alpha"], max_failure_examples=2)
    examples = rendered[rendered.index("#### Example failed checks") :]
    assert examples.index("`heavy`") < examples.index("`middle`")
    assert "`light`" not in examples.split("####")[1]
    assert "3 failing or errored check result(s)" in rendered
    # Rendering twice gives the same order.
    assert render(cells, ["alpha"], max_failure_examples=2) == rendered


def test_failed_examples_carry_evidence_and_the_raw_payload_reference() -> None:
    cells = perfect("alpha", {Criterion.CORPORATE_ACTION_ACCURACY: Outcome.FAIL})
    rendered = render(cells, ["alpha"])
    assert "- expected: expected value" in rendered
    assert "- observed: observed value" in rendered
    assert "`data/raw/alpha/prices/abc/payload.json`" in rendered


def test_expectation_review_failures_are_flagged_for_the_reader() -> None:
    from trp.bakeoff.payloads import EXPECTATION_REVIEW_PREFIX

    cells = [
        cell(
            [
                result(
                    Criterion.CORPORATE_ACTION_ACCURACY,
                    Outcome.FAIL,
                    "alpha",
                    explanation=f"{EXPECTATION_REVIEW_PREFIX}the ratio disagrees",
                )
            ],
            "alpha",
        )
    ]
    rendered = render(cells, ["alpha"])
    assert "the *expectation* behind this failure is itself unverified" in rendered


def measurement(explanation: str, *, provider: str = "alpha") -> CheckResult:
    from trp.bakeoff.payloads import MEASUREMENT_PREFIX

    return CheckResult(
        check="filing_lag_distribution",
        criterion=Criterion.PIT_FUNDAMENTALS,
        provider=provider,
        security_key="tesco",
        dataset=Dataset.FUNDAMENTALS,
        outcome=Outcome.NOT_APPLICABLE,
        observed="annual: n=6, median=88d, p90=101d",
        explanation=f"{MEASUREMENT_PREFIX}{explanation}",
    )


def test_measurement_findings_are_surfaced_without_being_scored() -> None:
    cells = [
        cell(
            [
                result(Criterion.HISTORICAL_DEPTH, Outcome.PASS, "alpha"),
                measurement("the sample is within DEC-007's assumed lag"),
            ],
            "alpha",
        )
    ]
    rendered = render(cells, ["alpha"])
    assert "#### Measurements" in rendered
    assert "p90=101d" in rendered
    # A measurement that agrees with the decision is one line, not a wall of prose.
    assert "within DEC-007's assumed lag" not in rendered
    # And it did not become a score.
    assert "no applicable check results" in rendered


def test_a_measurement_contradicting_a_decision_is_quoted_in_full() -> None:
    from trp.bakeoff.payloads import DECISION_TRIGGER

    cells = [
        cell(
            [
                result(Criterion.HISTORICAL_DEPTH, Outcome.PASS, "alpha"),
                measurement(f"{DECISION_TRIGGER}p90 101d EXCEEDS DEC-007's assumed 90d"),
            ],
            "alpha",
        )
    ]
    rendered = render(cells, ["alpha"])
    assert "1 measurement(s) contradict a recorded decision" in rendered
    assert "EXCEEDS DEC-007's assumed 90d" in rendered
    assert "superseding the decision, never by editing it" in rendered


def test_gaps_are_reported_as_prominently_as_results() -> None:
    cells = [
        cell([result(Criterion.HISTORICAL_DEPTH, Outcome.PASS, "alpha")], "alpha"),
        cell([], "alpha", dataset=Dataset.CORPORATE_ACTIONS, status=FetchStatus.RATE_LIMITED),
        cell([], "alpha", dataset=Dataset.SECURITIES, status=FetchStatus.PROVIDER_ERROR),
    ]
    rendered = render(cells, ["alpha"])
    assert "#### What was not measured" in rendered
    assert "| rate_limited | 1 |" in rendered
    assert "| provider_error | 1 |" in rendered


def test_evidence_table_names_the_checks_behind_each_criterion() -> None:
    cells = perfect("alpha")
    rendered = render(cells, ["alpha"])
    assert "#### Evidence behind each empirical score" in rendered
    assert "| corporate_action_accuracy | `chk` | 1 | 0 | 0 | 0 |" in rendered


# ------------------------------------------------------------------ recommendation


def test_close_totals_produce_an_explicitly_inconclusive_recommendation() -> None:
    # beta scores 0.5 on the lightest criterion: a 0.025 margin, inside what these ordinal
    # scores can support.
    beta = [
        *perfect("beta"),
        cell([result(Criterion.API_RELIABILITY, Outcome.FAIL, "beta")], "beta"),
    ]
    rendered = render(perfect("alpha") + beta, ["alpha", "beta"])
    assert "**Inconclusive.**" in rendered
    assert "declines to name a winner" in rendered
    assert "OWNER DECISION GATE" in rendered


def test_a_clear_margin_produces_a_recommendation_with_separating_evidence() -> None:
    cells = perfect("alpha") + perfect("beta", {Criterion.CORPORATE_ACTION_ACCURACY: Outcome.FAIL})
    rendered = render(cells, ["alpha", "beta"])
    assert "**Recommended: `alpha`**" in rendered
    assert "What separates them, heaviest first:" in rendered
    assert "corporate_action_accuracy" in rendered
    assert "Monthly cost:" in rendered
    assert "Main uncertainty:" in rendered


def test_when_every_candidate_is_vetoed_nothing_is_recommended() -> None:
    cells = perfect("alpha", {Criterion.DELISTED_COVERAGE: Outcome.FAIL}) + perfect(
        "beta", {Criterion.PIT_FUNDAMENTALS: Outcome.FAIL}
    )
    rendered = render(cells, ["alpha", "beta"])
    assert "No candidate is recommendable from this run." in rendered


def test_a_field_of_one_is_not_reported_as_a_winner() -> None:
    rendered = render(perfect("alpha"), ["alpha"])
    assert "A field of one is not a comparison" in rendered


def test_ordering_is_by_total_then_name() -> None:
    cells = perfect("beta") + perfect("alpha", {Criterion.CORPORATE_ACTION_ACCURACY: Outcome.FAIL})
    rendered = render(cells, ["alpha", "beta"])
    assert rendered.index("### beta") < rendered.index("### alpha")


def test_empty_run_renders_without_inventing_a_result() -> None:
    rendered = render([], [])
    assert "No provider scores were supplied for this run." in rendered
    assert "No candidate is recommendable" in rendered


# --------------------------------------------------------------------- end to end


def page(document: dict[str, Any]) -> RawPayload:
    return RawPayload(content=json.dumps(document).encode(), endpoint="/fake", params={})


def neutral_script() -> dict[Dataset, list[RawPayload | Exception]]:
    """One scripted response per dataset, in the neutral payload convention."""
    prices = {
        "rows": [
            {"date": "1995-01-03", "close": "100", "adjusted_close": "25"},
            {"date": "2014-06-06", "close": "400", "adjusted_close": "100"},
            {"date": "2020-08-28", "close": "500", "adjusted_close": "125"},
            {"date": "2020-08-31", "close": "125", "adjusted_close": "125"},
            {"date": "2026-01-02", "close": "180", "adjusted_close": "180"},
        ],
        "actions": [{"type": "split", "ex_date": "2020-08-31", "new_shares": 4, "old_shares": 1}],
    }
    actions = {
        "actions": [
            {"type": "split", "ex_date": "2020-08-31", "new_shares": 4, "old_shares": 1},
            {"type": "split", "ex_date": "2014-06-09", "ratio": "7:1"},
            {
                "type": "dividend",
                "ex_date": "2004-11-15",
                "amount": "3.00",
                "currency": "USD",
                "special": True,
            },
        ]
    }
    statements = {
        "statements": [
            {
                "period_end": "2019-12-31",
                "period_type": "annual",
                "filed_at": "2020-03-12",
                "currency": "GBP",
                "items": {"revenue": "1000"},
            },
            {
                "period_end": "2020-12-31",
                "period_type": "annual",
                "filed_at": "2021-04-05",
                "currency": "GBP",
                "items": {"revenue": "1100"},
            },
            {
                "period_end": "2014-08-23",
                "period_type": "interim",
                "filed_at": "2014-09-22",
                "revision": 1,
                "currency": "GBP",
                "items": {"trading_profit_guidance": "850000000"},
            },
        ]
    }
    return {
        Dataset.PRICES: [page(prices)],
        Dataset.CORPORATE_ACTIONS: [page(actions)],
        Dataset.FUNDAMENTALS: [page(statements)],
        Dataset.FINANCIAL_PERIODS: [page(statements)],
        Dataset.SECURITIES: [page({"rows": []})],
        Dataset.DELISTED_SECURITIES: [page({"rows": []})],
    }


def test_end_to_end_fake_provider_to_rendered_report(tmp_path: Path) -> None:
    universe = load_universe()
    summary = run_bakeoff(
        RunConfig(
            providers=[FakeProvider(neutral_script()), NoFundamentalsProvider(neutral_script())],
            universe=universe,
            raw_root=tmp_path / "raw",
            results_root=tmp_path / "results",
            run_id="end-to-end",
            markets=frozenset({Market.UK, Market.US}),
            checks=[*CORPORATE_ACTION_CHECKS, *PIT_FUNDAMENTAL_CHECKS],
            history_end=date(2026, 8, 16),
        )
    )
    run_metadata, cells = load_run(summary.run_dir)
    assert cells

    providers = sorted(run_metadata.providers)
    scores = [score_provider(name, cells, declared(name)) for name in providers]
    rendered = render_report(
        run_metadata,
        cells,
        scores,
        generated_at=run_metadata.started_at,
        declared=[d for name in providers for d in declared(name)],
        tiers=dict.fromkeys(providers, "test tier"),
        provisional=True,
        provisional_reason="Scripted fake provider, no live API call.",
    )

    assert rendered.startswith(RESULTS_HEADING)
    assert rendered.rstrip().endswith(GENERATED_END)
    assert "PROVISIONAL" in rendered
    for name in providers:
        assert f"### {name}" in rendered
    # Real check names from QNT-034/035 reached the evidence tables.
    assert "`split_ratio_and_ex_date`" in rendered
    assert "`fundamental_timestamp_presence`" in rendered
    assert "#### Measurements" in rendered  # the filing-lag measurement survived the round trip
    # The prices-only provider's missing fundamentals are a capability zero, not a gap in the
    # table, and it is therefore vetoed.
    assert "dataset(s) not offered by provider/tier" in rendered
    assert "UNSUITABLE" in rendered

    # And the whole thing lands in a copy of the real document without disturbing it.
    path = doc_copy(tmp_path)
    before = DOC.read_bytes()
    update_results_section(path, rendered)
    assert "## Method" in path.read_text()
    assert DOC.read_bytes() == before  # the real doc is untouched


def test_cli_renders_a_persisted_run_to_stdout(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    summary = run_bakeoff(
        RunConfig(
            providers=[FakeProvider(neutral_script())],
            universe=load_universe(),
            raw_root=tmp_path / "raw",
            results_root=tmp_path / "results",
            run_id="cli-run",
            markets=frozenset({Market.EU}),
            checks=[*CORPORATE_ACTION_CHECKS, *PIT_FUNDAMENTAL_CHECKS],
            history_end=date(2026, 8, 16),
        )
    )
    assert main(["--run-dir", str(summary.run_dir), "--provisional", "--tier", "fake=test"]) == 0
    printed = capsys.readouterr().out
    assert printed.startswith(RESULTS_HEADING)
    assert "PROVISIONAL" in printed
    assert "`cli-run`" in printed


def test_cli_updates_a_document_in_place(tmp_path: Path) -> None:
    summary = run_bakeoff(
        RunConfig(
            providers=[FakeProvider(neutral_script())],
            universe=load_universe(),
            raw_root=tmp_path / "raw",
            results_root=tmp_path / "results",
            run_id="cli-doc",
            markets=frozenset({Market.EU}),
            checks=[*CORPORATE_ACTION_CHECKS],
            history_end=date(2026, 8, 16),
        )
    )
    path = doc_copy(tmp_path)
    assert main(["--run-dir", str(summary.run_dir), "--doc", str(path)]) == 0
    first = path.read_bytes()
    assert main(["--run-dir", str(summary.run_dir), "--doc", str(path)]) == 0
    assert path.read_bytes() == first  # the CLI's default timestamp keeps it idempotent
