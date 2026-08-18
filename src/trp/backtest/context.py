"""The point-in-time context (QNT-050): the ONLY data path strategy code gets.

``as_of`` binds at construction for one simulated day and no method takes a
caller-chosen date — "read tomorrow's price" is not expressible. On a rebalance day the
context's clock is the previous session: the strategy decides with yesterday's
information (see BacktestConfig's timing convention).

Enforcement is structural (the engine holds full data; every accessor here filters to
``<= clock`` / ``available_at <= as_of``), and QNT-057's suites prove it behaviourally:
adding future-dated data to the inputs cannot change any result.
"""

from datetime import UTC, date, datetime, time, timedelta
from decimal import Decimal
from typing import TYPE_CHECKING

import polars as pl

from trp.domain.identifiers import SecurityId
from trp.factors.compute import ComputeContext, compute_factor
from trp.factors.definition import FactorDefinition
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
    ) -> None:
        self._clock = clock
        self._as_of = datetime.combine(clock, time(23, 59, 59), tzinfo=UTC)
        self._market = market
        self._universe_query = universe_query
        self._universe = universe
        self._mic = mic

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

    def factor_values(
        self, definition: FactorDefinition, security_ids: frozenset[SecurityId]
    ) -> pl.DataFrame:
        """Factor values computed AT the clock with the clock's knowledge — the compute
        surface receives only bars/actions the engine holds, and its as_of is ours."""
        context = ComputeContext(
            security_ids=sorted(security_ids),
            end=self._clock,
            as_of=self._as_of,
            bars=self._market.bars,
            actions=self._market.actions,
            input_versions=self._market.input_versions,
            mic=self._mic,
        )
        return compute_factor(definition, context)
