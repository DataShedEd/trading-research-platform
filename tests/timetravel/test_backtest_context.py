"""QNT-050 timetravel: the context is clock-bound — future data is structurally invisible.

The flagship test runs the SAME strategy over a dataset with and without future-dated
additions (bars after the window, actions announced later) and requires bit-identical
results. If any accessor leaks, this fails.
"""

from datetime import UTC, date, datetime, time
from decimal import Decimal

import pytest

from tests.backtest.test_engine import StubUniverse, make_config, make_market, run_engine
from tests.factors.test_returns import daily_bars
from trp.backtest.context import BacktestContext
from trp.domain.corporate_actions import Dividend
from trp.domain.identifiers import new_security_id
from trp.factors.registry import FactorRegistry

pytestmark = pytest.mark.timetravel

REGISTRY = FactorRegistry.load()
CLOCK = date(2021, 6, 30)


def make_context(market, universe=None):  # type: ignore[no-untyped-def]
    return BacktestContext(
        clock=CLOCK,
        market=market,
        universe_query=universe or StubUniverse(frozenset()),
        universe="TEST",
        mic="XLON",
    )


def test_price_is_the_last_close_on_or_before_the_clock() -> None:
    sid = new_security_id()
    bars = daily_bars(sid, date(2021, 1, 4), CLOCK, "100", {CLOCK: "111"})
    assert make_context(make_market(bars, [])).price(sid) == Decimal("111")


def test_price_ignores_bars_after_the_clock() -> None:
    sid = new_security_id()
    past = daily_bars(sid, date(2021, 1, 4), CLOCK, "100")
    future = daily_bars(sid, date(2021, 7, 1), date(2021, 12, 31), "999")
    assert make_context(make_market(past + future, [])).price(sid) == Decimal("100")


def test_price_refuses_stale_marks() -> None:
    sid = new_security_id()
    bars = daily_bars(sid, date(2021, 1, 4), date(2021, 6, 1), "100")  # 29 days stale
    assert make_context(make_market(bars, [])).price(sid) is None
    assert make_context(make_market([], [])).price(sid) is None


def test_membership_is_queried_with_the_clock_as_of() -> None:
    universe = StubUniverse(frozenset())
    make_context(make_market([], []), universe).members()
    assert universe.calls == [(CLOCK, datetime.combine(CLOCK, time(23, 59, 59), tzinfo=UTC))]


def test_factor_values_are_invariant_to_future_data() -> None:
    sid = new_security_id()
    past = daily_bars(sid, date(2020, 6, 1), CLOCK, "1000", {date(2021, 3, 1): "1100"})
    future_bars = daily_bars(sid, date(2021, 7, 1), date(2021, 12, 31), "5000")
    late_dividend = Dividend(
        security_id=sid,
        ex_date=date(2021, 2, 1),
        source="t",
        available_at=datetime(2021, 9, 1, tzinfo=UTC),
        amount=Decimal("50"),
        currency="GBX",
    )
    definition = REGISTRY.get("momentum_12_1")
    ids = frozenset({sid})
    clean = make_context(make_market(past, [])).factor_values(definition, ids)
    polluted = make_context(make_market(past + future_bars, [late_dividend])).factor_values(
        definition, ids
    )
    assert clean["value"].to_list() == polluted["value"].to_list()


def test_full_backtest_is_invariant_to_future_data() -> None:
    """Same config, same strategy; one dataset extended with future bars and
    late-announced actions. Every daily value and every ledger event must match."""
    a, b = new_security_id(), new_security_id()
    end = date(2021, 6, 30)
    past = daily_bars(a, date(2020, 11, 2), end, "100", {date(2021, 4, 1): "120"}) + daily_bars(
        b, date(2020, 11, 2), end, "200"
    )
    future = (
        daily_bars(a, date(2021, 7, 1), date(2021, 12, 31), "5")  # crash AFTER the window
        + daily_bars(b, date(2021, 7, 1), date(2021, 12, 31), "900")
    )
    late_actions = [
        Dividend(  # ex-date inside the window, announced after it ends
            security_id=a,
            ex_date=date(2021, 5, 4),
            source="t",
            available_at=datetime(2021, 8, 1, tzinfo=UTC),
            amount=Decimal("10"),
            currency="GBX",
        )
    ]

    def strategy(context: BacktestContext, positions: dict, value: Decimal) -> dict:  # type: ignore[type-arg]
        priced = [(s, context.price(s)) for s in sorted(context.members())]
        held = [s for s, p in priced if p is not None]
        return dict.fromkeys(held, 100)

    config = make_config(name="leakage-test", end=end)
    clean = run_engine(config, make_market(past, []), strategy)
    polluted = run_engine(config, make_market(past + future, late_actions), strategy)
    assert clean.daily.equals(polluted.daily)
    assert clean.events.equals(polluted.events)
