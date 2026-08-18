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
    MONTHLY = "monthly"  # first trading session of each calendar month
    QUARTERLY = "quarterly"  # first trading session of Jan/Apr/Jul/Oct


class Weighting(StrEnum):
    EQUAL = "equal"
    FACTOR_SCORE = "factor_score"
    INVERSE_VOLATILITY = "inverse_volatility"


class BacktestConfig(FrozenModel):
    name: str = Field(pattern=r"^[a-z0-9-]+$")
    start: date
    end: date
    universe: str
    mic: str = "XLON"
    factor: str
    factor_version: int = Field(ge=1)
    rebalance: RebalanceSchedule = RebalanceSchedule.MONTHLY
    weighting: Weighting = Weighting.EQUAL
    top_n: int = Field(gt=0)
    initial_cash: Decimal = Field(gt=0, description="in the exchange quote unit (GBX for XLON)")
    commission_bps: Decimal = Field(default=Decimal("2"), ge=0)
    spread_bps: Decimal = Field(default=Decimal("10"), ge=0)
    stamp_duty_bps: Decimal = Field(default=Decimal("50"), ge=0, description="UK: buys only")
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
