"""The frozen, fully serialisable backtest configuration — the reproducibility artefact.

A run is its config: re-running an identical ``BacktestConfig`` over identical data MUST
produce identical results (tested), and any single-field difference produces a different
``config_hash``. RESEARCH_METHODOLOGY's experiment records point at this object.

Simulation conventions captured here rather than implied:

- ``initial_cash`` is in the exchange's quote unit (GBX pence for XLON) — one unit
  everywhere in the ledger; presentation-layer conversion happens in metrics.
- Decision/execution timing: on a rebalance day the strategy sees data through the
  PREVIOUS session only (its ``as_of`` is the start of the rebalance day), and orders
  execute at the rebalance day's close. Deciding with yesterday's information and filling
  at today's close is honest on information and mildly optimistic on execution; the cost
  model (QNT-053) is where that optimism is paid for.
"""

import hashlib
from datetime import date
from decimal import Decimal
from enum import StrEnum
from typing import Self

from pydantic import Field, model_validator

from trp.domain.security import FrozenModel


class RebalanceSchedule(StrEnum):
    """Rebalances land on the (1 + offset)-th trading session of each period, so a
    period boundary falling on a weekend or holiday moves forward to the next session
    by construction rather than being skipped."""

    MONTHLY = "monthly"
    QUARTERLY = "quarterly"  # Jan/Apr/Jul/Oct
    ANNUALLY = "annually"  # January


class Weighting(StrEnum):
    EQUAL = "equal"
    FACTOR_SCORE = "factor_score"
    INVERSE_VOLATILITY = "inverse_volatility"


class Selection(StrEnum):
    TOP_N = "top_n"
    TOP_DECILE = "top_decile"
    THRESHOLD = "threshold"  # score >= selection_threshold


class NegativeScorePolicy(StrEnum):
    """Score-proportional weighting is undefined for negative scores (standardised
    composites produce them routinely) — the handling is configuration, never an
    implicit clamp."""

    RANK = "rank"  # weight by ascending rank position; sign-agnostic (default)
    SHIFT = "shift"  # weight by score minus the minimum score (minimum gets zero)
    POSITIVE_ONLY = "positive_only"  # drop non-positive scores entirely


class BacktestConfig(FrozenModel):
    name: str = Field(pattern=r"^[a-z0-9-]+$")
    start: date
    end: date
    universe: str
    mic: str = "XLON"
    factor: str
    factor_version: int = Field(ge=1)
    rebalance: RebalanceSchedule = RebalanceSchedule.MONTHLY
    rebalance_offset: int = Field(
        default=0, ge=0, description="trading sessions into the period (0 = first session)"
    )
    weighting: Weighting = Weighting.EQUAL
    selection: Selection = Selection.TOP_N
    selection_threshold: Decimal | None = None
    negative_scores: NegativeScorePolicy = NegativeScorePolicy.RANK
    top_n: int = Field(gt=0)
    max_holdings: int | None = Field(default=None, gt=0)
    max_weight: Decimal | None = Field(default=None, gt=0, le=1)
    min_weight: Decimal | None = Field(default=None, gt=0, le=1)
    invested_proportion: Decimal = Field(default=Decimal(1), gt=0, le=1)
    initial_cash: Decimal = Field(gt=0, description="in the exchange quote unit (GBX for XLON)")
    # Cost model (QNT-053). Defaults are deliberately pessimistic — RESEARCH_METHODOLOGY
    # rule 5 — and a test pins them to the documented floor.
    commission_bps: Decimal = Field(default=Decimal("2"), ge=0)
    commission_min: Decimal = Field(
        default=Decimal("500"), ge=0, description="per-trade minimum, quote units (500 GBX = £5)"
    )
    spread_bps: Decimal = Field(
        default=Decimal("10"), ge=0, description="full spread; half is charged per side"
    )
    stamp_duty_bps: Decimal = Field(default=Decimal("50"), ge=0, description="UK: buys only")
    impact_coefficient_bps: Decimal = Field(
        default=Decimal("25"),
        ge=0,
        description="market impact in bps per unit participation "
        "(order value / trailing median daily traded value)",
    )
    benchmark: str | None = None
    seed: int = 0
    data_versions: dict[str, str] = Field(default_factory=dict)

    @model_validator(mode="after")
    def _range_valid(self) -> Self:
        if self.end <= self.start:
            raise ValueError("end must be after start")
        return self

    def config_hash(self) -> str:
        return hashlib.sha256(self.model_dump_json().encode()).hexdigest()[:16]
