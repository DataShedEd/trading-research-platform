"""Scoring tests over synthetic check results — no harness run, no provider."""

from datetime import UTC, datetime
from decimal import Decimal

import pytest

from trp.bakeoff.checks import CheckResult, Criterion, Outcome
from trp.bakeoff.results import CellRecord, FetchStatus
from trp.bakeoff.scoring import (
    DeclaredScore,
    Weights,
    load_weights,
    score_provider,
)
from trp.providers.base import Dataset

NOW = datetime(2026, 8, 16, tzinfo=UTC)


def result(criterion: Criterion, outcome: Outcome, provider: str = "p") -> CheckResult:
    return CheckResult(
        check=f"chk-{criterion.value}",
        criterion=criterion,
        provider=provider,
        security_key="apple",
        dataset=Dataset.PRICES,
        outcome=outcome,
        explanation="synthetic",
    )


def cell(
    checks: list[CheckResult],
    provider: str = "p",
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


def declared(provider: str = "p") -> list[DeclaredScore]:
    return [
        DeclaredScore(provider=provider, criterion=c, score=Decimal(1), reason="research")
        for c in (Criterion.RATE_LIMITS_BULK, Criterion.LICENSING, Criterion.COST)
    ]


def all_empirical_pass(provider: str = "p") -> list[CellRecord]:
    empirical = [
        c
        for c in Criterion
        if c not in (Criterion.RATE_LIMITS_BULK, Criterion.LICENSING, Criterion.COST)
    ]
    return [cell([result(c, Outcome.PASS, provider) for c in empirical], provider)]


def test_weights_file_is_valid_and_versioned() -> None:
    weights = load_weights()
    assert weights.version == "2026-08-16.1"
    assert sum(weights.weights.values(), Decimal(0)) == Decimal(1)
    # The two non-negotiables carry the highest weights.
    top = sorted(weights.weights.items(), key=lambda kv: kv[1], reverse=True)[:2]
    assert {c for c, _ in top} == {Criterion.DELISTED_COVERAGE, Criterion.PIT_FUNDAMENTALS}


def test_weight_validation_rejects_bad_sums() -> None:
    weights = load_weights()
    broken = dict(weights.weights.items())
    broken[Criterion.COST] = Decimal("0.99")
    with pytest.raises(ValueError, match="sum to exactly 1"):
        Weights(
            version="x",
            weights=broken,
            declared_criteria=weights.declared_criteria,
        )


def test_perfect_provider_scores_one_everywhere() -> None:
    score = score_provider("p", all_empirical_pass(), declared())
    assert score.total == Decimal(1)
    assert not score.unsuitable
    assert all(b.score == Decimal(1) for b in score.breakdown)


def test_failing_the_heavy_criteria_ranks_below_failing_several_light_ones() -> None:
    heavy_fail = [
        cell(
            [
                result(Criterion.DELISTED_COVERAGE, Outcome.FAIL),
                result(Criterion.PIT_FUNDAMENTALS, Outcome.FAIL),
                result(Criterion.CORPORATE_ACTION_ACCURACY, Outcome.PASS),
                result(Criterion.IDENTIFIER_STABILITY, Outcome.PASS),
                result(Criterion.HISTORICAL_DEPTH, Outcome.PASS),
                result(Criterion.REVISION_HISTORY, Outcome.PASS),
                result(Criterion.API_RELIABILITY, Outcome.PASS),
            ]
        )
    ]
    light_fail = [
        cell(
            [
                result(Criterion.DELISTED_COVERAGE, Outcome.PASS),
                result(Criterion.PIT_FUNDAMENTALS, Outcome.PASS),
                result(Criterion.CORPORATE_ACTION_ACCURACY, Outcome.PASS),
                result(Criterion.IDENTIFIER_STABILITY, Outcome.PASS),
                result(Criterion.HISTORICAL_DEPTH, Outcome.PASS),
                result(Criterion.REVISION_HISTORY, Outcome.FAIL),
                result(Criterion.API_RELIABILITY, Outcome.FAIL),
            ]
        )
    ]
    heavy = score_provider("p", heavy_fail, declared())
    light = score_provider("p", light_fail, declared())
    assert heavy.total is not None and light.total is not None
    assert heavy.total < light.total
    # And the heavy failure trips both vetoes regardless of totals.
    assert heavy.unsuitable
    assert not light.unsuitable
    assert {b.criterion for b in heavy.breakdown if b.veto_failed} == {
        Criterion.DELISTED_COVERAGE,
        Criterion.PIT_FUNDAMENTALS,
    }


def test_not_applicable_excluded_from_denominator() -> None:
    cells = [
        cell(
            [
                result(Criterion.CORPORATE_ACTION_ACCURACY, Outcome.PASS),
                result(Criterion.CORPORATE_ACTION_ACCURACY, Outcome.NOT_APPLICABLE),
                result(Criterion.CORPORATE_ACTION_ACCURACY, Outcome.NOT_APPLICABLE),
            ]
        )
    ]
    score = score_provider("p", cells, declared())
    ca = next(b for b in score.breakdown if b.criterion is Criterion.CORPORATE_ACTION_ACCURACY)
    assert ca.score == Decimal(1)  # 1/1, not 1/3
    assert ca.coverage == 1


def test_errors_count_against_the_provider() -> None:
    cells = [
        cell(
            [
                result(Criterion.API_RELIABILITY, Outcome.PASS),
                result(Criterion.API_RELIABILITY, Outcome.ERROR),
            ]
        )
    ]
    score = score_provider("p", cells, declared())
    api = next(b for b in score.breakdown if b.criterion is Criterion.API_RELIABILITY)
    assert api.score == Decimal("0.5")


def test_unmeasured_is_distinct_from_zero_and_from_unsupported() -> None:
    # No fundamentals checks ran, but the dataset WAS supported: unmeasured.
    cells = [cell([result(Criterion.HISTORICAL_DEPTH, Outcome.PASS)])]
    score = score_provider("p", cells, declared())
    pit = next(b for b in score.breakdown if b.criterion is Criterion.PIT_FUNDAMENTALS)
    assert pit.score is None
    assert pit.unmeasured_reason == "no applicable check results"

    # The provider declares no fundamentals capability: zero, with the reason recorded.
    cells_unsupported = [
        *cells,
        cell([], dataset=Dataset.FUNDAMENTALS, status=FetchStatus.UNSUPPORTED),
    ]
    score2 = score_provider("p", cells_unsupported, declared())
    pit2 = next(b for b in score2.breakdown if b.criterion is Criterion.PIT_FUNDAMENTALS)
    assert pit2.score == Decimal(0)
    assert pit2.unmeasured_reason is not None
    assert "not offered" in pit2.unmeasured_reason
    # Zero on a veto criterion marks the provider unsuitable.
    assert score2.unsuitable


def test_declared_criteria_are_labelled_and_absent_inputs_unmeasured() -> None:
    score = score_provider("p", all_empirical_pass(), [])  # no declared inputs at all
    licensing = next(b for b in score.breakdown if b.criterion is Criterion.LICENSING)
    assert licensing.declared
    assert licensing.score is None
    assert licensing.unmeasured_reason == "no declared input supplied"
    # Total renormalises over measured criteria only.
    assert score.total == Decimal(1)


def test_determinism() -> None:
    a = score_provider("p", all_empirical_pass(), declared())
    b = score_provider("p", all_empirical_pass(), declared())
    assert a == b
