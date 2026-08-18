"""QNT-057 negative control: deliberately leaky engine variants MUST fail the scenarios.

If any of these tests starts failing, the scenario suite has quietly stopped asserting
anything — that is the alarm this module exists to ring. Two classic leaks:

- ``SameDayClockEngine`` decides with the FILL day's knowledge (trading at the
  signal-generating close).
- ``FinalMembershipUniverse`` resolves membership from end-state knowledge
  (survivorship: the dead never appear).
"""

from collections.abc import Sequence
from datetime import UTC, date, datetime
from decimal import Decimal

from tests.backtest.test_engine import (
    KNOWN,
    A,
    B,
    StubUniverse,
    daily_bars,
    make_config,
    make_market,
)
from trp.backtest.context import BacktestContext
from trp.backtest.engine import BacktestEngine, MarketData
from trp.domain.corporate_actions import DelistingAction, Dividend
from trp.domain.identifiers import SecurityId
from trp.domain.security import DelistingReason

END = date(2021, 6, 30)


class SameDayClockEngine(BacktestEngine):
    """The leak: the strategy sees the rebalance day's own close before 'trading' at it."""

    def _decision_clock(self, sessions: Sequence[date], index: int) -> date:
        return sessions[index]


class FinalMembershipUniverse(StubUniverse):
    """The leak: membership resolved from final knowledge — departures never existed."""

    def __init__(self, final_members: frozenset[SecurityId]) -> None:
        super().__init__(final_members)

    def members(self, universe, on, as_of=None):  # type: ignore[no-untyped-def, override]
        return self._members  # ignores both the date and the as_of: pure survivorship


def run_with(engine_class, market: MarketData, strategy, universe=None):  # type: ignore[no-untyped-def]
    engine = engine_class(make_config(), market, universe or StubUniverse(frozenset({A, B})))
    return engine.run(strategy)


def size_by_seen_price(context: BacktestContext, positions: dict, value: Decimal) -> dict:  # type: ignore[type-arg]
    if positions:
        return positions
    price = context.price(A)
    return {A: int(value / price)} if price else {}


def test_same_day_clock_fails_the_execution_price_scenario() -> None:
    """Price drops to 90 on the first rebalance day. Honest sizing sees the prior 100
    close and buys 10,000; the leaky engine sizes on the fill price itself and buys
    11,111 — more shares than same-day-blind information allows."""
    jump_day = date(2021, 1, 4)
    bars = daily_bars(A, date(2020, 11, 2), END, "100", {jump_day: "90", date(2021, 1, 5): "100"})
    market = make_market(bars, [])
    honest = run_with(BacktestEngine, market, size_by_seen_price)
    leaky = run_with(SameDayClockEngine, market, size_by_seen_price)
    honest_buy = honest.events.filter(honest.events["kind"] == "buy")
    leaky_buy = leaky.events.filter(leaky.events["kind"] == "buy")
    assert honest_buy["quantity_delta"].to_list() == [10000]  # hand: 1,000,000 / 100
    assert leaky_buy["quantity_delta"].to_list() == [11111]  # 1,000,000 / 90: the leak
    # Once the price recovers to 100, the leak shows up as free money.
    assert honest.daily["value"].to_list()[-1] == 1100000.0
    assert leaky.daily["value"].to_list()[-1] == 1111110.0


def test_same_day_clock_fails_the_knowledge_timing_scenario() -> None:
    """A dividend that went ex in late January is only PUBLISHED on the 1 Feb rebalance
    morning. The honest decision clock (29 Jan) cannot know it, so its momentum signal
    is still flat and it first buys a month later; the leaky same-day clock sees the
    announcement and buys immediately."""
    from trp.factors.registry import FactorRegistry

    definition = FactorRegistry.load().get("momentum_3_0")
    bars = daily_bars(A, date(2020, 6, 1), END, "100")
    late_news = Dividend(
        security_id=A,
        ex_date=date(2021, 1, 25),
        source="t",
        available_at=datetime(2021, 2, 1, 8, 0, tzinfo=UTC),  # published a week later
        amount=Decimal("7"),
        currency="GBX",
    )

    def buy_on_momentum(context: BacktestContext, positions: dict, value: Decimal) -> dict:  # type: ignore[type-arg]
        if positions:
            return positions
        frame = context.factor_values(definition, frozenset({A}))
        row = frame.to_dicts()[0]
        if row["status"] == "ok" and row["value"] is not None and row["value"] > 0.03:
            return {A: 100}
        return positions

    market = make_market(bars, [late_news])
    honest = run_with(BacktestEngine, market, buy_on_momentum)
    leaky = run_with(SameDayClockEngine, market, buy_on_momentum)
    honest_buys = honest.events.filter(honest.events["kind"] == "buy")["on"].to_list()
    leaky_buys = leaky.events.filter(leaky.events["kind"] == "buy")["on"].to_list()
    assert honest_buys == ["2021-03-01"]  # first clock that can know the announcement
    assert leaky_buys == ["2021-02-01"]  # the leak trades on same-morning knowledge


def equal_weight_members(context: BacktestContext, positions: dict, value: Decimal) -> dict:  # type: ignore[type-arg]
    members = sorted(context.members())
    if not members:
        return {}
    per_name = value / len(members)
    targets = {}
    for security_id in members:
        price = context.price(security_id)
        if price:
            targets[security_id] = int(per_name / price)
    return targets


def test_final_membership_fails_the_survivorship_scenario() -> None:
    """B fails mid-window. The honest universe holds B until it dies and eats the
    write-off; the final-membership universe never held it — history looks cleaner
    than it was, by exactly the loss it dodged."""
    bars = daily_bars(A, date(2020, 11, 2), END, "100") + daily_bars(
        B, date(2020, 11, 2), date(2021, 2, 26), "100"
    )
    failure = DelistingAction(
        security_id=B,
        ex_date=date(2021, 3, 1),
        source="t",
        available_at=KNOWN,
        reason=DelistingReason.FAILURE,
        last_trading_date=date(2021, 2, 26),
    )

    class HonestUniverse(StubUniverse):
        def members(self, universe, on, as_of=None):  # type: ignore[no-untyped-def, override]
            return frozenset({A, B}) if on < date(2021, 3, 1) else frozenset({A})

    market = make_market(bars, [failure])
    honest = run_with(BacktestEngine, market, equal_weight_members, HonestUniverse(frozenset()))
    leaky = run_with(
        BacktestEngine, market, equal_weight_members, FinalMembershipUniverse(frozenset({A}))
    )
    # Hand: honest buys 5,000 of each at 100; B's 500,000 resolves to zero on 1 Mar
    # (a failure delisting books as delisting_proceeds at 0 per DEC-017).
    losses = honest.events.filter(honest.events["note"] == "delisting (failure)")
    assert losses.height == 1
    assert losses["cash_delta"].to_list() == ["0"]
    assert honest.daily["value"].to_list()[-1] == 500000.0
    # The leaky run never touched B: full value intact, the loss silently dodged.
    assert "delisting (failure)" not in leaky.events["note"].to_list()
    assert leaky.daily["value"].to_list()[-1] == 1000000.0
