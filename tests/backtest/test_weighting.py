"""QNT-052: selection, weighting schemes and position limits against hand-computed fixtures."""

import pytest

from trp.backtest.config import NegativeScorePolicy, Selection
from trp.backtest.weighting import (
    WeightingError,
    apply_limits,
    equal_weights,
    inverse_volatility_weights,
    ranked,
    score_weights,
    select,
)
from trp.domain.identifiers import SecurityId

A, B, C, D = (SecurityId(x) for x in ("id-a", "id-b", "id-c", "id-d"))


def test_ranking_breaks_ties_deterministically() -> None:
    assert ranked({B: 1.0, A: 1.0, C: 2.0}) == [C, A, B]


def test_top_n_selection() -> None:
    scores = {A: 3.0, B: 1.0, C: 2.0}
    assert select(scores, Selection.TOP_N, top_n=2) == [A, C]


def test_top_decile_selection_rounds_up() -> None:
    scores = {SecurityId(f"id-{i:02d}"): float(i) for i in range(13)}
    chosen = select(scores, Selection.TOP_DECILE, top_n=999)
    assert len(chosen) == 2  # ceil(13 / 10)
    assert chosen == [SecurityId("id-12"), SecurityId("id-11")]


def test_threshold_selection() -> None:
    scores = {A: 0.3, B: -0.1, C: 0.1}
    assert select(scores, Selection.THRESHOLD, top_n=99, threshold=0.1) == [A, C]
    with pytest.raises(WeightingError, match="selection_threshold"):
        select(scores, Selection.THRESHOLD, top_n=99)


def test_max_holdings_truncates_the_selection() -> None:
    scores = {A: 3.0, B: 2.0, C: 1.0}
    assert select(scores, Selection.TOP_N, top_n=3, max_holdings=2) == [A, B]


def test_equal_weights_sum_to_invested_proportion() -> None:
    weights = equal_weights([A, B, C], invested=0.9)
    assert weights == {A: 0.3, B: 0.3, C: 0.3}
    assert equal_weights([], 1.0) == {}


def test_score_weights_positive_only() -> None:
    weights = score_weights({A: 2.0, B: 1.0, C: -1.0}, NegativeScorePolicy.POSITIVE_ONLY)
    assert weights == {A: pytest.approx(2 / 3), B: pytest.approx(1 / 3)}
    with pytest.raises(WeightingError, match="no positive scores"):
        score_weights({A: -1.0, B: -2.0}, NegativeScorePolicy.POSITIVE_ONLY)


def test_score_weights_shift() -> None:
    # Shifted scores: 4, 2, 0 -> weights 4/6, 2/6, 0.
    weights = score_weights({A: 3.0, B: 1.0, C: -1.0}, NegativeScorePolicy.SHIFT)
    assert weights == {A: pytest.approx(4 / 6), B: pytest.approx(2 / 6), C: 0.0}
    # All-equal scores degenerate to equal weighting rather than 0/0.
    assert score_weights({A: 5.0, B: 5.0}, NegativeScorePolicy.SHIFT) == {A: 0.5, B: 0.5}


def test_score_weights_rank() -> None:
    # Worst-first ranks: C=1, B=2, A=3, total 6 — sign-agnostic.
    weights = score_weights({A: 3.0, B: 1.0, C: -100.0}, NegativeScorePolicy.RANK)
    assert weights == {C: pytest.approx(1 / 6), B: pytest.approx(2 / 6), A: pytest.approx(3 / 6)}


def test_inverse_volatility_weights() -> None:
    weights = inverse_volatility_weights({A: 0.1, B: 0.2})
    assert weights == {A: pytest.approx(2 / 3), B: pytest.approx(1 / 3)}
    with pytest.raises(WeightingError, match="non-positive volatility"):
        inverse_volatility_weights({A: 0.0})


def test_max_weight_cap_redistributes_pro_rata() -> None:
    # Hand-worked: cap A at 0.34, redistribute 0.66 over B:C = 0.3:0.1 -> 0.495/0.165;
    # B now exceeds the cap too -> cap B, C absorbs the remaining 0.32.
    weights = apply_limits({A: 0.6, B: 0.3, C: 0.1}, max_weight=0.34)
    assert weights == {A: 0.34, B: 0.34, C: pytest.approx(0.32)}
    assert sum(weights.values()) == pytest.approx(1.0)


def test_infeasible_max_weight_raises() -> None:
    with pytest.raises(WeightingError, match="cannot invest"):
        apply_limits({A: 0.5, B: 0.5}, max_weight=0.4)


def test_min_weight_drops_and_redistributes() -> None:
    weights = apply_limits({A: 0.5, B: 0.45, C: 0.05}, min_weight=0.1)
    assert weights == {A: pytest.approx(0.5 / 0.95), B: pytest.approx(0.45 / 0.95)}
    assert sum(weights.values()) == pytest.approx(1.0)
    with pytest.raises(WeightingError, match="drops every position"):
        apply_limits({A: 0.02, B: 0.03}, min_weight=0.9)


def test_min_and_max_limits_compose() -> None:
    weights = apply_limits({A: 0.7, B: 0.28, C: 0.02}, max_weight=0.6, min_weight=0.1)
    assert sum(weights.values()) == pytest.approx(1.0)
    assert all(0.1 <= w <= 0.6 + 1e-12 for w in weights.values())
    assert C not in weights
