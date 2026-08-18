"""QNT-057: end-to-end scenarios with hand-computed expected outcomes.

Every expected number below was worked out on paper before running the code (the world is
built to keep them exact): flat 100 GBX prices, 10 bps commission as the only cost, and a
buy-and-hold strategy of 1,000 shares. A scenario whose expectation came from running the
code would be a change detector, not a correctness test.

Common ground for every scenario:
- initial cash 1,000,000 GBX
- first rebalance (2021-01-04): buy 1,000 @ 100 -> notional 100,000, commission 100
- cash after entry 899,900; portfolio value 999,900 (the 100 GBX cost is the only leak)
- the equity curve starts at the FIRST session's close, i.e. at 999,900 post-entry, so
  `total_return` denominators below are 999,900, not the initial cash

Each scenario also reconciles end-to-end: gross return minus costs equals net return, and
cumulative reported costs equal the ledger's explicit cost debits.
"""

from datetime import date
from decimal import Decimal

import pytest

from tests.backtest.test_engine import (
    KNOWN,
    A,
    daily_bars,
    make_config,
    make_market,
    run_engine,
)
from trp.backtest.context import BacktestContext
from trp.backtest.metrics import compute_metrics
from trp.domain.corporate_actions import DelistingAction, Dividend, Merger, Split
from trp.domain.security import DelistingReason

END = date(2021, 6, 30)
COSTED = {"commission_bps": Decimal("10"), "commission_min": Decimal(0)}


def hold_1000(context: BacktestContext, positions: dict, value: Decimal) -> dict:  # type: ignore[type-arg]
    return {A: 1000}


def reconcile(result, market, strategy) -> None:  # type: ignore[no-untyped-def]
    """Costs decompose exactly: reported per-rebalance costs equal the ledger's explicit
    cost debits, and the costed run's final value differs from a ZERO-cost run of the
    identical scenario by exactly those costs (prices are flat, so nothing else moves)."""
    ledger_costs = sum(Decimal(c) for c in result.events["costs"].to_list())
    reported = sum(result.rebalances["costs"].to_list())
    assert float(ledger_costs) == pytest.approx(reported)
    gross = run_engine(make_config(), market, strategy)  # same world, zero costs
    gross_final = gross.daily["value"].to_list()[-1]
    net_final = result.daily["value"].to_list()[-1]
    assert gross_final - net_final == pytest.approx(float(ledger_costs))


def test_scenario_dividends_credited_once_each() -> None:
    """Ordinary 7p (ex 1 Mar) and special 50p (ex 1 Apr) on 1,000 held shares.

    Hand: 999,900 + 7,000 + 50,000 = 1,056,900 final; net 57,000/999,900."""
    bars = daily_bars(A, date(2020, 11, 2), END, "100")
    actions = [
        Dividend(
            security_id=A,
            ex_date=date(2021, 3, 1),
            source="t",
            available_at=KNOWN,
            amount=Decimal("7"),
            currency="GBX",
        ),
        Dividend(
            security_id=A,
            ex_date=date(2021, 4, 1),
            source="t",
            available_at=KNOWN,
            amount=Decimal("50"),
            currency="GBX",
            special=True,
        ),
    ]
    market = make_market(bars, actions)
    result = run_engine(make_config(**COSTED), market, hold_1000)
    dividends = result.events.filter(result.events["kind"] == "dividend")
    assert dividends.height == 2  # once each, never twice
    assert dividends["on"].to_list() == ["2021-03-01", "2021-04-01"]  # ex-date timing
    assert result.daily["value"].to_list()[-1] == 1056900.0
    assert result.daily["cash"].to_list()[-1] == 956900.0
    record = compute_metrics(result.daily.select("date", "value"), result.events)
    assert record.total_return == pytest.approx(57000 / 999900)
    reconcile(result, market, hold_1000)


def test_scenario_consolidation_no_artificial_jump() -> None:
    """1-for-2 consolidation (ex 1 Mar): 1,000 shares @100 become 500 @200.

    Hand: value 999,900 on every day after entry — the event moves nothing."""
    ex = date(2021, 3, 1)
    bars = daily_bars(A, date(2020, 11, 2), END, "100", {ex: "200"})
    split = Split(
        security_id=A, ex_date=ex, source="t", available_at=KNOWN, new_shares=1, old_shares=2
    )

    def hold_current(context: BacktestContext, positions: dict, value: Decimal) -> dict:  # type: ignore[type-arg]
        return positions or {A: 1000}

    market = make_market(bars, [split])
    result = run_engine(make_config(**COSTED), market, hold_current)
    assert set(result.daily["value"].to_list()) == {999900.0}  # no jump anywhere
    splits = result.events.filter(result.events["kind"] == "split")
    assert splits["quantity_delta"].to_list() == [-500]
    assert result.events.filter(result.events["kind"] == "cash_in_lieu").height == 0
    reconcile(result, market, hold_current)


def test_scenario_delisting_with_proceeds() -> None:
    """Cash takeover at 120 GBX (ex 1 Apr, knowable in advance).

    Hand: 899,900 + 1,000 x 120 = 1,019,900; position gone; net 20,000/999,900."""
    bars = daily_bars(A, date(2020, 11, 2), date(2021, 3, 31), "100")
    merger = Merger(
        security_id=A,
        ex_date=date(2021, 4, 1),
        source="t",
        available_at=KNOWN,
        cash_amount=Decimal("120"),
        cash_currency="GBX",
    )
    market = make_market(bars, [merger])
    result = run_engine(make_config(**COSTED), market, hold_1000)
    assert result.daily["value"].to_list()[-1] == 1019900.0
    assert result.daily["positions"].to_list()[-1] == 0  # never a phantom holding
    record = compute_metrics(result.daily.select("date", "value"), result.events)
    assert record.total_return == pytest.approx(20000 / 999900)
    reconcile(result, market, hold_1000)


def test_scenario_delisting_as_total_loss() -> None:
    """Failure delisting: the position writes off to zero.

    Hand: 899,900 final; net -100,000/999,900 (the write-off; entry cost already in the base)."""
    bars = daily_bars(A, date(2020, 11, 2), date(2021, 3, 31), "100")
    failure = DelistingAction(
        security_id=A,
        ex_date=date(2021, 4, 1),
        source="t",
        available_at=KNOWN,
        reason=DelistingReason.FAILURE,
        last_trading_date=date(2021, 3, 31),
    )
    market = make_market(bars, [failure])
    result = run_engine(make_config(**COSTED), market, hold_1000)
    assert result.daily["value"].to_list()[-1] == 899900.0
    record = compute_metrics(result.daily.select("date", "value"), result.events)
    assert record.total_return == pytest.approx(-100000 / 999900)
    reconcile(result, market, hold_1000)


def test_scenario_turnover_and_costs_reconcile_over_a_round_trip() -> None:
    """Buy 1,000 @100 in January, sell all in February, hold cash after.

    Hand: costs 100 + 100; final 999,800; per-rebalance one-way turnover 5% each leg."""
    bars = daily_bars(A, date(2020, 11, 2), END, "100")

    def flip(context: BacktestContext, positions: dict, value: Decimal) -> dict:  # type: ignore[type-arg]
        return {} if positions or context.today >= date(2021, 2, 1) else {A: 1000}

    market = make_market(bars, [])
    result = run_engine(make_config(**COSTED), market, flip)
    assert result.daily["value"].to_list()[-1] == 999800.0
    active = result.rebalances.filter(result.rebalances["trades"] > 0)
    # First leg on a 1,000,000 pre-trade value, second on 999,900 (post entry cost).
    assert active["turnover"].to_list() == [
        pytest.approx(100000 / 2 / 1000000),
        pytest.approx(100000 / 2 / 999900),
    ]
    assert active["costs"].to_list() == [pytest.approx(100.0), pytest.approx(100.0)]
    reconcile(result, market, flip)
