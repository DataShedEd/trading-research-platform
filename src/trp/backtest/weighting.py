"""Selection, weighting and position limits (QNT-052): pure functions, no data access.

Everything here maps scores (and volatilities) that the caller already obtained through a
clock-bound context into target weights. Determinism is load-bearing: every ordering
tie-breaks on the security id, so two runs over the same inputs produce identical
portfolios.

Documented rules:
- Negative scores under FACTOR_SCORE weighting follow the configured
  ``NegativeScorePolicy`` (rank / shift / positive-only) — never an implicit clamp.
- ``max_holdings`` truncates the SELECTION (keeping the best-scored names) before any
  weighting happens.
- ``max_weight`` capping redistributes the excess pro-rata across uncapped names,
  iterating until no name exceeds the cap; if the cap is infeasible
  (n * max_weight < invested proportion) that is a ``WeightingError``, not a silent
  under-investment.
- ``min_weight`` then drops any name below the floor and redistributes to the survivors
  (re-applying the cap), iterating to a fixed point.
"""

import math

from trp.backtest.config import NegativeScorePolicy, Selection
from trp.domain.identifiers import SecurityId


class WeightingError(Exception):
    pass


def ranked(scores: dict[SecurityId, float]) -> list[SecurityId]:
    """Security ids best-score-first; ties break on the id itself for determinism."""
    return sorted(scores, key=lambda s: (-scores[s], s))


def select(
    scores: dict[SecurityId, float],
    rule: Selection,
    *,
    top_n: int,
    threshold: float | None = None,
    max_holdings: int | None = None,
) -> list[SecurityId]:
    ordered = ranked(scores)
    if rule is Selection.TOP_N:
        chosen = ordered[:top_n]
    elif rule is Selection.TOP_DECILE:
        chosen = ordered[: max(1, math.ceil(len(ordered) / 10))] if ordered else []
    elif rule is Selection.THRESHOLD:
        if threshold is None:
            raise WeightingError("THRESHOLD selection requires selection_threshold")
        chosen = [s for s in ordered if scores[s] >= threshold]
    else:  # pragma: no cover - exhaustive over the enum
        raise WeightingError(f"unknown selection rule {rule}")
    if max_holdings is not None:
        chosen = chosen[:max_holdings]
    return chosen


def equal_weights(selected: list[SecurityId], invested: float = 1.0) -> dict[SecurityId, float]:
    if not selected:
        return {}
    return {s: invested / len(selected) for s in selected}


def score_weights(
    scores: dict[SecurityId, float],
    policy: NegativeScorePolicy,
    invested: float = 1.0,
) -> dict[SecurityId, float]:
    """Weight proportionally to score under the configured negative-score policy."""
    if not scores:
        return {}
    if policy is NegativeScorePolicy.POSITIVE_ONLY:
        positive = {s: v for s, v in scores.items() if v > 0}
        if not positive:
            raise WeightingError("POSITIVE_ONLY policy with no positive scores")
        total = sum(positive.values())
        return {s: invested * v / total for s, v in positive.items()}
    if policy is NegativeScorePolicy.SHIFT:
        minimum = min(scores.values())
        shifted = {s: v - minimum for s, v in scores.items()}
        total = sum(shifted.values())
        if total == 0:  # all scores equal: shift degenerates, fall back to equal
            return equal_weights(sorted(scores), invested)
        return {s: invested * v / total for s, v in shifted.items()}
    # RANK: 1 for the worst score up to n for the best; sign-agnostic.
    worst_first = ranked(scores)[::-1]
    n = len(worst_first)
    total_ranks = n * (n + 1) / 2
    return {s: invested * (i + 1) / total_ranks for i, s in enumerate(worst_first)}


def inverse_volatility_weights(
    volatilities: dict[SecurityId, float], invested: float = 1.0
) -> dict[SecurityId, float]:
    for security_id, vol in volatilities.items():
        if vol <= 0:
            raise WeightingError(f"non-positive volatility for {security_id}: {vol}")
    if not volatilities:
        return {}
    inverse = {s: 1.0 / v for s, v in volatilities.items()}
    total = sum(inverse.values())
    return {s: invested * v / total for s, v in inverse.items()}


def apply_limits(
    weights: dict[SecurityId, float],
    *,
    max_weight: float | None = None,
    min_weight: float | None = None,
) -> dict[SecurityId, float]:
    """Enforce position limits per the documented redistribution rules (module docstring)."""
    if not weights:
        return {}
    invested = sum(weights.values())
    current = dict(weights)
    for _ in range(len(weights) + 1):  # each pass either converges or drops a name
        current = _cap(current, max_weight, invested)
        if min_weight is None:
            return current
        below = [s for s, w in current.items() if w < min_weight - 1e-12]
        if not below:
            return current
        survivors = {s: w for s, w in current.items() if s not in set(below)}
        if not survivors:
            raise WeightingError("min_weight drops every position")
        scale = invested / sum(survivors.values())
        current = {s: w * scale for s, w in survivors.items()}
    raise WeightingError("position limits did not converge")  # pragma: no cover


def _cap(
    weights: dict[SecurityId, float], max_weight: float | None, invested: float
) -> dict[SecurityId, float]:
    if max_weight is None:
        return weights
    if len(weights) * max_weight < invested - 1e-12:
        raise WeightingError(
            f"max_weight {max_weight} over {len(weights)} names cannot invest {invested}"
        )
    capped: dict[SecurityId, float] = {}
    free = dict(weights)
    while True:
        over = [s for s, w in free.items() if w > max_weight + 1e-12]
        if not over:
            return {**capped, **free}
        for s in over:
            capped[s] = max_weight
            del free[s]
        remaining = invested - sum(capped.values())
        if not free:
            return capped  # everything at the cap; feasibility check above guarantees sum
        free_total = sum(free.values())
        free = {s: remaining * w / free_total for s, w in free.items()}
