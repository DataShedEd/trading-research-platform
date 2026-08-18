"""The point-in-time context (QNT-050): the ONLY data path strategy code gets.

``as_of`` binds at construction for one simulated day and no method takes a
caller-chosen date — "read tomorrow's price" is not expressible. On a rebalance day the
context's clock is the previous session: the strategy decides with yesterday's
information (see BacktestConfig's timing convention).

Enforcement is structural (the engine holds full data; every accessor here filters to
``<= clock`` / ``available_at <= as_of``), and QNT-057's suites prove it behaviourally:
adding future-dated data to the inputs cannot change any result.
"""

from bisect import bisect_left
from datetime import UTC, date, datetime, time, timedelta
from decimal import Decimal
from typing import TYPE_CHECKING

import polars as pl

from trp.derived.adjustments import MAX_PREV_CLOSE_GAP_DAYS
from trp.domain.corporate_actions import CorporateAction
from trp.domain.identifiers import SecurityId
from trp.domain.prices import DailyBar
from trp.factors.compute import ComputeContext, compute_factor
from trp.factors.definition import FactorDefinition
from trp.factors.returns import ReturnBasis, ReturnsEngine
from trp.universe.query import UniverseQuery

if TYPE_CHECKING:
    from trp.backtest.engine import MarketData

_MARK_STALENESS_DAYS = 15


class BacktestContext:
    def __init__(
        self,
        *,
        clock: date,
        market: "MarketData",
        universe_query: UniverseQuery,
        universe: str,
        mic: str,
        factor_lookback_days: int = 450,
    ) -> None:
        self._clock = clock
        self._as_of = datetime.combine(clock, time(23, 59, 59), tzinfo=UTC)
        self._market = market
        self._universe_query = universe_query
        self._universe = universe
        self._mic = mic
        # Bars/actions handed to factor computation are sliced to this many calendar days
        # before the clock — enough for a 12-1 momentum window plus volatility estimation.
        # A factor needing deeper history must raise this, never silently compute short.
        self._factor_lookback_days = factor_lookback_days
        self._returns_by_sid: dict[SecurityId, ReturnsEngine] = {}

    @property
    def today(self) -> date:
        return self._clock

    def members(self) -> frozenset[SecurityId]:
        return self._universe_query.members(self._universe, self._clock, as_of=self._as_of)

    def price(self, security_id: SecurityId) -> Decimal | None:
        """Last raw close on-or-before the clock, or None if absent/stale."""
        found = self._market.close_on_or_before(security_id, self._clock)
        if found is None:
            return None
        bar_date, close = found
        if (self._clock - bar_date) > timedelta(days=_MARK_STALENESS_DAYS):
            return None
        return close

    def realised_volatility(
        self, security_id: SecurityId, window_sessions: int = 126
    ) -> float | None:
        """Sample stdev of daily total returns over the trailing window, computed from the
        SAME adjusted series the returns library uses, truncated to the clock. Unannualised
        — weighting normalises the scale away. None below 21 observations."""
        series = self._returns_engine(security_id).adjusted_series(security_id, ReturnBasis.TOTAL)
        past = [value for day, value in series if day <= self._clock]
        window = past[-(window_sessions + 1) :]
        if len(window) < 21:
            return None
        returns = [window[i] / window[i - 1] - 1 for i in range(1, len(window))]
        mean = sum(returns) / len(returns)
        variance = sum((r - mean) ** 2 for r in returns) / (len(returns) - 1)
        return float(variance**0.5)

    def _returns_engine(self, security_id: SecurityId) -> ReturnsEngine:
        engine = self._returns_by_sid.get(security_id)
        if engine is None:
            bars, actions = self._sliced_inputs(frozenset({security_id}))
            engine = ReturnsEngine(bars, actions, as_of=self._as_of, mic=self._mic)
            self._returns_by_sid[security_id] = engine
        return engine

    def _lookback_start(self) -> date:
        return self._clock - timedelta(days=self._factor_lookback_days)

    def _sliced_inputs(
        self, security_ids: frozenset[SecurityId]
    ) -> tuple[list[DailyBar], list[CorporateAction]]:
        """Bars over the lookback window plus the actions computable AGAINST those bars.

        An action whose ex-date is on or before a security's first sliced bar has no
        anchor close inside the window; excluding it is exact, because a pre-window
        adjustment multiplies every in-window value by the same constant and cancels in
        any within-window ratio."""
        bars = self._market.bars_for(security_ids, self._lookback_start(), self._clock)
        dates_by_sid: dict[SecurityId, list[date]] = {}
        for bar in bars:  # bars_for returns each security's bars in ascending date order
            dates_by_sid.setdefault(bar.security_id, []).append(bar.trade_date)
        # A pre-window action cancels in any within-window ratio and is dropped exactly.
        # A security whose IN-window action cannot anchor (bar gap wider than the
        # adjustment engine tolerates — a suspension) is excluded from this computation
        # entirely: its factor is unknowable at this clock, and it was untradeable anyway.
        unanchorable: set[SecurityId] = set()
        actions: list[CorporateAction] = []
        for action in self._market.actions_for(security_ids):
            dates = dates_by_sid.get(action.security_id)
            # Outside the security's sliced span the action multiplies every in-window
            # value equally (before) or none of them (after) — either way it cancels.
            if dates is None or action.ex_date <= dates[0] or action.ex_date > dates[-1]:
                continue
            index = bisect_left(dates, action.ex_date)
            previous = dates[index - 1]
            if (action.ex_date - previous).days > MAX_PREV_CLOSE_GAP_DAYS:
                unanchorable.add(action.security_id)
                continue
            actions.append(action)
        if unanchorable:
            bars = [b for b in bars if b.security_id not in unanchorable]
            actions = [a for a in actions if a.security_id not in unanchorable]
        return bars, actions

    def factor_values(
        self, definition: FactorDefinition, security_ids: frozenset[SecurityId]
    ) -> pl.DataFrame:
        """Factor values computed AT the clock with the clock's knowledge — the compute
        surface receives only bars/actions the engine holds, and its as_of is ours."""
        bars, actions = self._sliced_inputs(security_ids)
        context = ComputeContext(
            security_ids=sorted(security_ids),
            end=self._clock,
            as_of=self._as_of,
            bars=bars,
            actions=actions,
            input_versions=self._market.input_versions,
            mic=self._mic,
        )
        return compute_factor(definition, context)
