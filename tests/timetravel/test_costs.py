"""QNT-053 timetravel: the liquidity input to market impact is point-in-time — volume
data recorded after a trade date can never change that trade's cost."""

from datetime import date
from decimal import Decimal

import pytest

from tests.backtest.test_engine import A, daily_bars, make_config, make_market, run_engine
from trp.backtest.context import BacktestContext
from trp.backtest.engine import MarketData
from trp.domain.security import revalidated_copy

pytestmark = pytest.mark.timetravel

END = date(2021, 6, 30)


def test_median_traded_value_ignores_later_volume() -> None:
    past = daily_bars(A, date(2021, 1, 4), END, "100")
    # Enormous volume printed after END must not move the median at END.
    future = [
        revalidated_copy(bar, volume=10**9)
        for bar in daily_bars(A, date(2021, 7, 1), date(2021, 12, 31), "100")
    ]
    clean = MarketData(past, [], {})
    polluted = MarketData(past + future, [], {})
    assert clean.median_traded_value(A, END) == polluted.median_traded_value(A, END)


def test_historical_trade_costs_are_invariant_to_future_volume() -> None:
    config = make_config(
        commission_bps=Decimal("2"),
        commission_min=Decimal("500"),
        spread_bps=Decimal("10"),
        stamp_duty_bps=Decimal("50"),
        impact_coefficient_bps=Decimal("25"),
    )
    past = daily_bars(A, date(2020, 11, 2), END, "100")
    future = daily_bars(A, date(2021, 7, 1), date(2021, 12, 31), "100")

    def churn(context: BacktestContext, positions: dict, value: Decimal) -> dict:  # type: ignore[type-arg]
        return {} if positions else {A: 500}

    clean = run_engine(config, make_market(past, []), churn)
    polluted = run_engine(config, make_market(past + future, []), churn)
    assert clean.rebalances["costs"].to_list() == polluted.rebalances["costs"].to_list()
    assert clean.events.equals(polluted.events)
