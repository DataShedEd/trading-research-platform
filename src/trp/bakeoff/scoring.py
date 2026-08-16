"""Scoring: hundreds of check results -> an honest, pre-registered comparison.

Weights live in ``weights.json`` — versioned data, fixed before any real provider result
existed, so the rubric is a decision procedure rather than a rationalisation. Scores are
exact ``Decimal`` arithmetic (DEC-005): identical inputs give byte-identical tables.

Semantics:

- A criterion's empirical score is passes / (passes + fails + errors) over the checks
  mapped to it; ``not_applicable`` results are excluded from the denominator entirely.
- A criterion with no applicable results is **unmeasured** (``score=None``) — never zero,
  never full marks — and is excluded from the weighted total, which renormalises over the
  measured criteria (the breakdown shows exactly which).
- A provider that lacks a dataset outright (``unsupported`` fetches) scores **zero** on
  criteria whose checks could then never run, with the reason recorded — being unable to
  serve fundamentals is a real deficiency, not an unmeasured one.
- Declared criteria (licensing, cost, rate limits — from QNT-028's research, not from API
  checks) enter as :class:`DeclaredScore` inputs and are labelled as declared in the
  breakdown, because they carry different evidential weight.
- Veto thresholds (DEC-012): a measured score below the threshold on a veto criterion
  marks the provider **unsuitable** regardless of total — QUANT_PRINCIPLES §1/§2 are
  non-negotiable and cannot be averaged away.

Scores are ordinal, not cardinal: 0.82 vs 0.79 is not a meaningful difference. The
breakdown, coverage counts and veto flags are the real output; the total is a summary.
"""

import json
from collections import defaultdict
from collections.abc import Iterable, Sequence
from decimal import Decimal
from pathlib import Path
from typing import Self

from pydantic import Field, model_validator

from trp.bakeoff.checks import CheckResult, Criterion, Outcome
from trp.bakeoff.results import CellRecord, FetchStatus
from trp.domain.security import FrozenModel, revalidated_copy
from trp.providers.base import Dataset

WEIGHTS_PATH = Path(__file__).parent / "weights.json"

# Which criteria depend on which dataset kinds: an unsupported dataset zeroes these.
_CRITERION_DATASETS: dict[Criterion, frozenset[Dataset]] = {
    Criterion.DELISTED_COVERAGE: frozenset({Dataset.DELISTED_SECURITIES, Dataset.PRICES}),
    Criterion.PIT_FUNDAMENTALS: frozenset({Dataset.FUNDAMENTALS, Dataset.FINANCIAL_PERIODS}),
    Criterion.REVISION_HISTORY: frozenset({Dataset.FUNDAMENTALS}),
    Criterion.CORPORATE_ACTION_ACCURACY: frozenset({Dataset.CORPORATE_ACTIONS}),
    Criterion.HISTORICAL_DEPTH: frozenset({Dataset.PRICES}),
    Criterion.IDENTIFIER_STABILITY: frozenset({Dataset.SECURITIES}),
}


class WeightsError(Exception):
    pass


class Weights(FrozenModel):
    version: str
    comment: str | None = None
    weights: dict[Criterion, Decimal]
    declared_criteria: tuple[Criterion, ...]
    veto_thresholds: dict[Criterion, Decimal] = Field(default_factory=dict)

    @model_validator(mode="after")
    def _complete_and_normalised(self) -> Self:
        missing = set(Criterion) - set(self.weights)
        if missing:
            raise ValueError(f"weights missing for {sorted(c.value for c in missing)}")
        total = sum(self.weights.values(), Decimal(0))
        if total != Decimal(1):
            raise ValueError(f"weights must sum to exactly 1, got {total}")
        return self


def load_weights(path: Path = WEIGHTS_PATH) -> Weights:
    try:
        return Weights.model_validate(json.loads(path.read_text()))
    except (OSError, json.JSONDecodeError) as exc:
        raise WeightsError(str(exc)) from exc


class DeclaredScore(FrozenModel):
    """A researched, non-empirical input (QNT-028): licensing, cost, rate limits."""

    provider: str
    criterion: Criterion
    score: Decimal = Field(ge=0, le=1)
    reason: str = Field(min_length=1)


class CriterionScore(FrozenModel):
    criterion: Criterion
    score: Decimal | None  # None = unmeasured
    weight: Decimal
    coverage: int  # how many check results informed it — read a 3-check score accordingly
    declared: bool
    contribution: Decimal | None
    unmeasured_reason: str | None = None
    veto_failed: bool = False


class ProviderScore(FrozenModel):
    provider: str
    weights_version: str
    total: Decimal | None
    unsuitable: bool
    breakdown: tuple[CriterionScore, ...]


def score_provider(
    provider: str,
    cells: Sequence[CellRecord],
    declared: Iterable[DeclaredScore] = (),
    weights: Weights | None = None,
) -> ProviderScore:
    rubric = weights if weights is not None else load_weights()
    provider_cells = [c for c in cells if c.provider == provider]
    declared_by_criterion = {d.criterion: d for d in declared if d.provider == provider}

    unsupported_datasets = {
        c.dataset for c in provider_cells if c.fetch_status is FetchStatus.UNSUPPORTED
    }
    results_by_criterion: dict[Criterion, list[CheckResult]] = defaultdict(list)
    for cell in provider_cells:
        for result in cell.checks:
            results_by_criterion[result.criterion].append(result)

    breakdown: list[CriterionScore] = []
    for criterion in Criterion:
        weight = rubric.weights[criterion]
        if criterion in rubric.declared_criteria:
            fact = declared_by_criterion.get(criterion)
            if fact is None:
                breakdown.append(
                    CriterionScore(
                        criterion=criterion,
                        score=None,
                        weight=weight,
                        coverage=0,
                        declared=True,
                        contribution=None,
                        unmeasured_reason="no declared input supplied",
                    )
                )
            else:
                breakdown.append(
                    CriterionScore(
                        criterion=criterion,
                        score=fact.score,
                        weight=weight,
                        coverage=1,
                        declared=True,
                        contribution=None,  # filled after renormalisation
                    )
                )
            continue

        needed = _CRITERION_DATASETS.get(criterion, frozenset())
        blocked = needed & unsupported_datasets
        applicable = [
            r
            for r in results_by_criterion.get(criterion, [])
            if r.outcome is not Outcome.NOT_APPLICABLE
        ]
        if blocked and not applicable:
            breakdown.append(
                CriterionScore(
                    criterion=criterion,
                    score=Decimal(0),
                    weight=weight,
                    coverage=0,
                    declared=False,
                    contribution=None,
                    unmeasured_reason=(
                        "dataset(s) not offered by provider/tier: "
                        + ", ".join(sorted(d.value for d in blocked))
                    ),
                )
            )
            continue
        if not applicable:
            breakdown.append(
                CriterionScore(
                    criterion=criterion,
                    score=None,
                    weight=weight,
                    coverage=0,
                    declared=False,
                    contribution=None,
                    unmeasured_reason="no applicable check results",
                )
            )
            continue
        passes = sum(1 for r in applicable if r.outcome is Outcome.PASS)
        score = Decimal(passes) / Decimal(len(applicable))
        breakdown.append(
            CriterionScore(
                criterion=criterion,
                score=score,
                weight=weight,
                coverage=len(applicable),
                declared=False,
                contribution=None,
            )
        )

    measured = [b for b in breakdown if b.score is not None]
    weight_sum = sum((b.weight for b in measured), Decimal(0))
    finished: list[CriterionScore] = []
    total: Decimal | None = None
    if measured and weight_sum > 0:
        total = Decimal(0)
        for b in breakdown:
            if b.score is None:
                finished.append(b)
                continue
            contribution = (b.weight / weight_sum) * b.score
            total += contribution
            finished.append(revalidated_copy(b, contribution=contribution))
    else:
        finished = breakdown

    unsuitable = False
    flagged: list[CriterionScore] = []
    for b in finished:
        threshold = rubric.veto_thresholds.get(b.criterion)
        if threshold is not None and b.score is not None and b.score < threshold:
            unsuitable = True
            flagged.append(revalidated_copy(b, veto_failed=True))
        else:
            flagged.append(b)

    return ProviderScore(
        provider=provider,
        weights_version=rubric.version,
        total=total,
        unsuitable=unsuitable,
        breakdown=tuple(flagged),
    )
