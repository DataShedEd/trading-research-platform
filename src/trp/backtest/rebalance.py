"""Rebalance scheduling, trade generation and the factor-strategy composer (QNT-052).

Scheduling works in TRADING SESSIONS, so a period boundary on a weekend or holiday moves
forward to the period's next session by construction. Turnover is one-way:
(buy value + sell value) / 2, over the pre-trade portfolio value.

`factor_strategy` is the standard composition the tearsheet runs: universe members ->
factor scores -> selection -> weighting -> position limits -> whole-share targets. All
inputs come through the clock-bound context (signals and sizing prices are the PREVIOUS
session's; fills happen at the rebalance day's close — the DEC-017 convention), so the
execution price is always the next available price after the signal.

Exit rule: a security that leaves the universe or the selection simply drops out of the
target dict, and the engine's order diff sells it at the rebalance close. Delistings
BETWEEN rebalances are ledger events (QNT-051), never phantom holds.
"""

from collections.abc import Sequence
from datetime import date
from decimal import Decimal

from trp.backtest.config import BacktestConfig, RebalanceSchedule, Weighting
from trp.backtest.context import BacktestContext
from trp.backtest.weighting import (
    apply_limits,
    equal_weights,
    inverse_volatility_weights,
    score_weights,
    select,
)
from trp.domain.identifiers import SecurityId
from trp.factors.definition import FactorDefinition

_PERIOD_MONTHS = {
    RebalanceSchedule.MONTHLY: frozenset(range(1, 13)),
    RebalanceSchedule.QUARTERLY: frozenset({1, 4, 7, 10}),
    RebalanceSchedule.ANNUALLY: frozenset({1}),
}


def rebalance_sessions(
    sessions: Sequence[date], schedule: RebalanceSchedule, offset: int = 0
) -> frozenset[date]:
    """The (1 + offset)-th session of each scheduled period, counted within the period's
    first calendar month; an offset past that month's sessions rebalances on the month's
    last session rather than skipping the period."""
    months = _PERIOD_MONTHS[schedule]
    by_period: dict[tuple[int, int], list[date]] = {}
    for session in sessions:
        if session.month in months:
            by_period.setdefault((session.year, session.month), []).append(session)
    return frozenset(days[min(offset, len(days) - 1)] for days in by_period.values())


def target_shares(
    weights: dict[SecurityId, float],
    portfolio_value: Decimal,
    prices: dict[SecurityId, Decimal],
) -> dict[SecurityId, int]:
    """Whole-share targets: floor(weight * value / price). Names without a price are
    unsizeable and excluded — the diff will exit any existing holding."""
    targets: dict[SecurityId, int] = {}
    for security_id in sorted(weights):
        price = prices.get(security_id)
        if price is None or price <= 0:
            continue
        shares = int(Decimal(str(weights[security_id])) * portfolio_value / price)
        if shares > 0:
            targets[security_id] = shares
    return targets


def one_way_turnover(fills: Sequence[tuple[int, Decimal]], pre_trade_value: Decimal) -> float:
    """(buys + sells) / 2 over the pre-trade portfolio value; fills are signed shares."""
    if pre_trade_value <= 0:
        return 0.0
    traded = sum((abs(shares) * price for shares, price in fills), start=Decimal(0))
    return float(traded / 2 / pre_trade_value)


def factor_strategy(definition: FactorDefinition, config: BacktestConfig) -> "_FactorStrategy":
    return _FactorStrategy(definition, config)


class _FactorStrategy:
    def __init__(self, definition: FactorDefinition, config: BacktestConfig) -> None:
        if definition.name != config.factor or definition.version != config.factor_version:
            raise ValueError(
                f"definition {definition.name}@{definition.version} does not match "
                f"config factor {config.factor}@{config.factor_version}"
            )
        self._definition = definition
        self._config = config

    def __call__(
        self,
        context: BacktestContext,
        positions: dict[SecurityId, int],
        portfolio_value: Decimal,
    ) -> dict[SecurityId, int]:
        config = self._config
        members = context.members()
        frame = context.factor_values(self._definition, members)
        scores = {
            SecurityId(row["security_id"]): float(row["value"])
            for row in frame.iter_rows(named=True)
            if row["status"] == "ok" and row["value"] is not None
        }
        chosen = select(
            scores,
            config.selection,
            top_n=config.top_n,
            threshold=(
                float(config.selection_threshold)
                if config.selection_threshold is not None
                else None
            ),
            max_holdings=config.max_holdings,
        )
        invested = float(config.invested_proportion)
        if config.weighting is Weighting.EQUAL:
            weights = equal_weights(chosen, invested)
        elif config.weighting is Weighting.FACTOR_SCORE:
            weights = score_weights(
                {s: scores[s] for s in chosen}, config.negative_scores, invested
            )
        else:
            volatilities = {}
            for security_id in chosen:
                vol = context.realised_volatility(security_id)
                if vol is not None and vol > 0:
                    volatilities[security_id] = vol
            weights = inverse_volatility_weights(volatilities, invested)
        weights = apply_limits(
            weights,
            max_weight=float(config.max_weight) if config.max_weight is not None else None,
            min_weight=float(config.min_weight) if config.min_weight is not None else None,
        )
        prices = {s: context.price(s) for s in weights}
        return target_shares(
            weights, portfolio_value, {s: p for s, p in prices.items() if p is not None}
        )
