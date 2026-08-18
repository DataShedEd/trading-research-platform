"""The transaction-cost model (QNT-053): pessimistic by default, explicit in the ledger.

Costs are charged as explicit cash debits (a `costs` field on every trade event), never by
shading the execution price — that is what lets any result be decomposed into gross
return, costs, and net return, and lets reported totals reconcile exactly against the
ledger.

Components per trade, all parameterised in ``BacktestConfig`` (RESEARCH_METHODOLOGY
rule 5):
- Commission: ``commission_bps`` of notional with a ``commission_min`` per-trade floor.
- Half-spread: ``spread_bps / 2`` of notional, charged on BOTH sides.
- UK stamp duty: ``stamp_duty_bps`` (0.5% default) on PURCHASES only. Exemptions (AIM
  securities in particular) are a security-level predicate supplied by the caller; the
  default is that NOTHING is exempt, which is the pessimistic side of an uncertain rule.
- Market impact: ``impact_coefficient_bps x participation`` of notional, where
  participation = order value / trailing 60-session MEDIAN daily traded value
  (close x volume), computed only from bars on or before the trade date. A security with
  no usable volume history is assumed to be fully the order's size (participation 1) —
  illiquidity is never free.
"""

from dataclasses import dataclass
from decimal import Decimal
from enum import StrEnum
from typing import Protocol

from trp.backtest.config import BacktestConfig
from trp.domain.identifiers import SecurityId

_BPS = Decimal("0.0001")

IMPACT_WINDOW_SESSIONS = 60
"""Trailing sessions for the median daily traded value."""


class Side(StrEnum):
    BUY = "buy"
    SELL = "sell"


class StampExemption(Protocol):
    def __call__(self, security_id: SecurityId) -> bool: ...


def no_exemptions(security_id: SecurityId) -> bool:
    """The pessimistic default: stamp duty applies to every purchase."""
    return False


@dataclass(frozen=True)
class TradeCosts:
    commission: Decimal
    spread: Decimal
    stamp_duty: Decimal
    impact: Decimal

    @property
    def total(self) -> Decimal:
        return self.commission + self.spread + self.stamp_duty + self.impact


class CostModel:
    def __init__(
        self, config: BacktestConfig, is_stamp_exempt: StampExemption = no_exemptions
    ) -> None:
        self._config = config
        self._is_stamp_exempt = is_stamp_exempt

    def cost(
        self,
        security_id: SecurityId,
        side: Side,
        notional: Decimal,
        median_daily_value: Decimal | None,
    ) -> TradeCosts:
        """Cost of trading ``notional`` (quote units) against the given liquidity.

        ``median_daily_value`` must be computed from data available at the trade date
        only — the engine supplies it from bars on or before the fill day."""
        if notional <= 0:
            raise ValueError(f"notional must be positive, got {notional}")
        config = self._config
        commission = max(notional * config.commission_bps * _BPS, config.commission_min)
        spread = notional * (config.spread_bps / 2) * _BPS
        stamp = Decimal(0)
        if side is Side.BUY and not self._is_stamp_exempt(security_id):
            stamp = notional * config.stamp_duty_bps * _BPS
        if median_daily_value is not None and median_daily_value > 0:
            participation = notional / median_daily_value
        else:
            participation = Decimal(1)  # no liquidity evidence: assume we ARE the volume
        impact = notional * config.impact_coefficient_bps * _BPS * participation
        return TradeCosts(commission=commission, spread=spread, stamp_duty=stamp, impact=impact)
