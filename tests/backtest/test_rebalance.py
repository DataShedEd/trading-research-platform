"""QNT-052: schedules over the real calendar, trade sizing, turnover, and the
factor-strategy composition (including the execution-price convention)."""

from datetime import date
from decimal import Decimal

import pytest

from tests.backtest.test_engine import (
    A,
    B,
    StubUniverse,
    daily_bars,
    make_config,
    make_market,
    run_engine,
)
from trp.backtest.config import RebalanceSchedule
from trp.backtest.context import BacktestContext
from trp.backtest.rebalance import (
    factor_strategy,
    one_way_turnover,
    rebalance_sessions,
    target_shares,
)
from trp.canonical.calendars import get_trading_calendar
from trp.domain.identifiers import SecurityId, new_security_id
from trp.factors.registry import FactorRegistry

CAL = get_trading_calendar("XLON")
REGISTRY = FactorRegistry.load()
SESSIONS_2021_H1 = CAL.sessions_between(date(2021, 1, 1), date(2021, 6, 30))


def test_monthly_schedule_moves_holiday_boundaries_forward() -> None:
    days = sorted(rebalance_sessions(SESSIONS_2021_H1, RebalanceSchedule.MONTHLY))
    # 3 May 2021 is a bank holiday: the May rebalance lands on the 4th, never skipped.
    assert days == [
        date(2021, 1, 4),
        date(2021, 2, 1),
        date(2021, 3, 1),
        date(2021, 4, 1),
        date(2021, 5, 4),
        date(2021, 6, 1),
    ]


def test_offset_counts_trading_sessions_not_calendar_days() -> None:
    days = sorted(rebalance_sessions(SESSIONS_2021_H1, RebalanceSchedule.MONTHLY, offset=2))
    assert days[0] == date(2021, 1, 6)  # third session of January
    assert days[4] == date(2021, 5, 6)  # May: 4th, 5th, 6th


def test_quarterly_and_annual_schedules() -> None:
    quarterly = sorted(rebalance_sessions(SESSIONS_2021_H1, RebalanceSchedule.QUARTERLY))
    assert quarterly == [date(2021, 1, 4), date(2021, 4, 1)]
    annual = sorted(rebalance_sessions(SESSIONS_2021_H1, RebalanceSchedule.ANNUALLY))
    assert annual == [date(2021, 1, 4)]


def test_target_shares_floor_and_skip_unpriced() -> None:
    a, b, c = sorted([new_security_id(), new_security_id(), new_security_id()])
    weights = {a: 0.5, b: 0.3, c: 0.2}
    prices = {a: Decimal("300"), b: Decimal("70")}  # c has no price -> excluded
    targets = target_shares(weights, Decimal("10000"), prices)
    assert targets == {a: 16, b: 42}  # floor(5000/300)=16, floor(3000/70)=42


def test_one_way_turnover_hand_computed() -> None:
    fills = [(10, Decimal("100")), (-5, Decimal("200"))]  # 1000 bought + 1000 sold
    assert one_way_turnover(fills, Decimal("10000")) == pytest.approx(0.1)
    assert one_way_turnover([], Decimal("10000")) == 0.0
    assert one_way_turnover(fills, Decimal("0")) == 0.0


def test_factor_strategy_rejects_mismatched_definition() -> None:
    definition = REGISTRY.get("momentum_12_1")
    with pytest.raises(ValueError, match="does not match"):
        factor_strategy(definition, make_config(factor="momentum_6_1"))


def momentum_world() -> tuple:
    """A rising and a flat security with enough history for momentum_12_1 at mid-2021."""
    rising = daily_bars(A, date(2019, 12, 2), date(2021, 6, 30), "100", {date(2020, 9, 1): "150"})
    flat = daily_bars(B, date(2019, 12, 2), date(2021, 6, 30), "200")
    return rising, flat


def make_context(market, members: frozenset[SecurityId], clock: date) -> BacktestContext:  # type: ignore[no-untyped-def]
    return BacktestContext(
        clock=clock,
        market=market,
        universe_query=StubUniverse(members),  # type: ignore[arg-type]
        universe="TEST",
        mic="XLON",
    )


def test_factor_strategy_selects_and_sizes_from_the_context() -> None:
    rising, flat = momentum_world()
    config = make_config(top_n=1)
    strategy = factor_strategy(REGISTRY.get("momentum_12_1"), config)
    context = make_context(make_market(rising + flat, []), frozenset({A, B}), date(2021, 6, 1))
    targets = strategy(context, {}, Decimal("1000000"))
    # A has +50% momentum, B zero; top-1 equal weight -> all in A at its clock price 150.
    assert targets == {A: 6666}  # floor(1000000 / 150)


def test_universe_leavers_drop_out_of_the_targets() -> None:
    rising, flat = momentum_world()
    config = make_config(top_n=2)
    strategy = factor_strategy(REGISTRY.get("momentum_12_1"), config)
    market = make_market(rising + flat, [])
    both = strategy(
        make_context(market, frozenset({A, B}), date(2021, 6, 1)), {}, Decimal("1000000")
    )
    assert set(both) == {A, B}
    # B leaves the universe: even while holding B, the target no longer contains it,
    # and the engine's order diff sells it (documented exit rule).
    only_a = strategy(
        make_context(market, frozenset({A}), date(2021, 6, 1)), {B: 100}, Decimal("1000000")
    )
    assert set(only_a) == {A}


def test_execution_uses_the_next_price_not_the_signal_close() -> None:
    """Signal and sizing come from the decision session; the fill is the NEXT session's
    close — the pessimistic side of the convention, recorded as DEC-017."""
    jump_day = date(2021, 2, 1)  # a rebalance execution day
    bars = daily_bars(A, date(2020, 11, 2), date(2021, 6, 30), "100", {jump_day: "110"})
    sized_with: list[Decimal] = []

    def buy_with_seen_price(context: BacktestContext, positions: dict, value: Decimal) -> dict:  # type: ignore[type-arg]
        if positions or context.today < date(2021, 1, 20):
            return positions
        price = context.price(A)
        assert price is not None
        sized_with.append(price)
        return {A: int(value / price)}

    result = run_engine(make_config(), make_market(bars, []), buy_with_seen_price)
    assert sized_with == [Decimal("100")]  # decided on the pre-jump close
    buys = result.events.filter(result.events["kind"] == "buy")
    assert buys["price"].to_list() == ["110"]  # filled at the jump-day close
    # Sized 10000 shares at 100 but paying 110: the affordability clamp trims the order
    # rather than allowing negative cash.
    assert buys["quantity_delta"].to_list() == [9090]  # floor(1000000 / 110)


def test_engine_reports_turnover_per_rebalance() -> None:
    bars = daily_bars(A, date(2020, 11, 2), date(2021, 6, 30), "100")

    def flip(context: BacktestContext, positions: dict, value: Decimal) -> dict:  # type: ignore[type-arg]
        return {} if positions else {A: 1000}

    result = run_engine(make_config(), make_market(bars, []), flip)
    turnover = result.rebalances["turnover"].to_list()
    # Buy 1000 @ 100 (traded 100000, value 1000000 -> 0.05 one-way), then sell it all,
    # alternating each month.
    assert turnover == [pytest.approx(0.05)] * 6
    assert result.rebalances["trades"].to_list() == [1] * 6
    assert result.rebalances["traded_value"].to_list() == [pytest.approx(100000.0)] * 6
