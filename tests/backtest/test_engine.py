"""QNT-050: the daily loop over a synthetic world — calendar, rebalancing, actions,
reproducibility, run records."""

import json
from datetime import UTC, date, datetime
from decimal import Decimal
from pathlib import Path

import pytest

from tests.factors.test_returns import daily_bars
from trp.backtest.config import BacktestConfig, RebalanceSchedule
from trp.backtest.context import BacktestContext
from trp.backtest.engine import BacktestEngine, MarketData, write_run
from trp.backtest.portfolio import LedgerError
from trp.canonical.calendars import get_trading_calendar
from trp.domain.corporate_actions import DelistingAction, Dividend, Merger, Split
from trp.domain.identifiers import SecurityId, new_security_id
from trp.domain.security import DelistingReason

CAL = get_trading_calendar("XLON")
START = date(2021, 1, 1)
END = date(2021, 6, 30)
KNOWN = datetime(2020, 12, 31, tzinfo=UTC)  # everything knowable before the run starts

A = new_security_id()
B = new_security_id()
C = new_security_id()


class StubUniverse:
    """Stands in for UniverseQuery: fixed membership, records every as_of it is asked."""

    def __init__(self, members: frozenset[SecurityId]) -> None:
        self._members = members
        self.calls: list[tuple[date, datetime | None]] = []

    def members(
        self, universe: str, on: date, as_of: datetime | None = None
    ) -> frozenset[SecurityId]:
        self.calls.append((on, as_of))
        return self._members


def make_config(**overrides: object) -> BacktestConfig:
    values: dict[str, object] = {
        "name": "engine-test",
        "start": START,
        "end": END,
        "universe": "TEST",
        "factor": "momentum_12_1",
        "factor_version": 1,
        "top_n": 3,
        "initial_cash": Decimal("1000000"),
        "commission_bps": Decimal(0),
        "commission_min": Decimal(0),
        "spread_bps": Decimal(0),
        "stamp_duty_bps": Decimal(0),
        "impact_coefficient_bps": Decimal(0),
    }
    values.update(overrides)
    return BacktestConfig(**values)  # type: ignore[arg-type]


def make_market(bars: list, actions: list) -> MarketData:  # type: ignore[type-arg]
    return MarketData(bars, actions, {"prices": "test"})


def flat_world() -> MarketData:
    bars = (
        daily_bars(A, date(2020, 11, 2), END, "100")
        + daily_bars(B, date(2020, 11, 2), END, "200")
        + daily_bars(C, date(2020, 11, 2), END, "400")
    )
    return make_market(bars, [])


def hold_a(context: BacktestContext, positions: dict, value: Decimal) -> dict:  # type: ignore[type-arg]
    return {A: 100}


def run_engine(config: BacktestConfig, market: MarketData, strategy=hold_a):  # type: ignore[no-untyped-def]
    engine = BacktestEngine(config, market, StubUniverse(frozenset({A, B, C})))  # type: ignore[arg-type]
    return engine.run(strategy)


def test_loop_visits_exactly_the_exchange_sessions() -> None:
    result = run_engine(make_config(), flat_world())
    assert result.daily["date"].to_list() == list(CAL.sessions_between(START, END))


def test_monthly_rebalances_decide_on_the_previous_session() -> None:
    decision_days: list[date] = []

    def recorder(context: BacktestContext, positions: dict, value: Decimal) -> dict:  # type: ignore[type-arg]
        decision_days.append(context.today)
        return {}

    run_engine(make_config(), flat_world(), recorder)
    sessions = CAL.sessions_between(START, END)
    first_of_month = [
        s for i, s in enumerate(sessions) if i == 0 or s.month != sessions[i - 1].month
    ]
    assert len(decision_days) == 6  # Jan..Jun
    for decision, execution in zip(decision_days, first_of_month, strict=True):
        assert decision == CAL.previous_trading_day(execution)


def test_quarterly_schedule_rebalances_in_january_and_april_only() -> None:
    count = 0

    def counter(context: BacktestContext, positions: dict, value: Decimal) -> dict:  # type: ignore[type-arg]
        nonlocal count
        count += 1
        return {}

    run_engine(make_config(rebalance=RebalanceSchedule.QUARTERLY), flat_world(), counter)
    assert count == 2  # Jan and Apr within Jan-Jun


def test_two_runs_are_identical() -> None:
    first = run_engine(make_config(), flat_world())
    second = run_engine(make_config(), flat_world())
    assert first.daily.equals(second.daily)
    assert first.events.equals(second.events)


def test_buy_and_hold_accounting() -> None:
    result = run_engine(make_config(), flat_world())
    # 100 shares of A at 100, zero costs: cash 990000, value flat at 1000000 throughout.
    assert set(result.daily["value"].to_list()) == {1000000.0}
    assert result.daily["cash"].to_list()[-1] == 990000.0


def test_costs_are_charged_on_execution() -> None:
    config = make_config(
        commission_bps=Decimal("2"), spread_bps=Decimal("10"), stamp_duty_bps=Decimal("50")
    )
    result = run_engine(config, flat_world())
    # One initial buy of 100 A at 100 = 10000 notional; later rebalances are no-ops.
    # Buy-side rate = (2 + 5 + 50) bps = 0.57% -> 57 in costs.
    assert result.daily["value"].to_list()[-1] == 1000000.0 - 57.0


def test_dividend_credits_on_ex_date_for_held_shares() -> None:
    ex = date(2021, 3, 1)
    dividend = Dividend(
        security_id=A,
        ex_date=ex,
        source="t",
        available_at=KNOWN,
        amount=Decimal("7"),
        currency="GBX",
    )
    bars = daily_bars(A, date(2020, 11, 2), END, "100")
    result = run_engine(make_config(), make_market(bars, [dividend]))
    daily = dict(zip(result.daily["date"], result.daily["value"], strict=True))
    before = CAL.previous_trading_day(ex)
    assert daily[ex] == daily[before] + 700.0  # 100 shares * 7p


def test_split_preserves_value_with_cash_in_lieu() -> None:
    ex = date(2021, 3, 1)
    split = Split(
        security_id=A, ex_date=ex, source="t", available_at=KNOWN, new_shares=3, old_shares=2
    )
    bars = daily_bars(A, date(2020, 11, 2), END, "100", {ex: "66.6"})

    def buy_odd(context: BacktestContext, positions: dict, value: Decimal) -> dict:  # type: ignore[type-arg]
        return positions or {A: 101}  # 101 * 3/2 = 151.5 -> cash in lieu path

    result = run_engine(make_config(), make_market(bars, [split]), buy_odd)
    daily = dict(zip(result.daily["date"], result.daily["value"], strict=True))
    before = CAL.previous_trading_day(ex)
    # 151.5 * 66.6 = 10089.9 vs 101 * 100 = 10100 -> only the mark move, no value jump from
    # the share-count mechanics themselves.
    assert daily[ex] == pytest.approx(daily[before] - 101 * 100 + 151.5 * 66.6)


def test_failure_delisting_writes_the_position_off() -> None:
    ex = date(2021, 4, 1)
    delisting = DelistingAction(
        security_id=A,
        ex_date=ex,
        source="t",
        available_at=KNOWN,
        reason=DelistingReason.FAILURE,
        last_trading_date=date(2021, 3, 31),
    )
    bars = daily_bars(A, date(2020, 11, 2), date(2021, 3, 31), "100")
    result = run_engine(make_config(), make_market(bars, [delisting]))
    daily = dict(zip(result.daily["date"], result.daily["value"], strict=True))
    assert daily[END] == 990000.0  # the 10000 position is a total loss
    positions = dict(zip(result.daily["date"], result.daily["positions"], strict=True))
    assert positions[ex] == 0


def test_merger_cash_consideration_pays_out() -> None:
    ex = date(2021, 4, 1)
    merger = Merger(
        security_id=A,
        ex_date=ex,
        source="t",
        available_at=KNOWN,
        cash_amount=Decimal("120"),
        cash_currency="GBX",
    )
    bars = daily_bars(A, date(2020, 11, 2), date(2021, 3, 31), "100")
    result = run_engine(make_config(), make_market(bars, [merger]))
    daily = dict(zip(result.daily["date"], result.daily["value"], strict=True))
    assert daily[END] == 1000000.0 + 100 * 20.0  # bought at 100, taken out at 120


def test_order_without_same_day_print_is_skipped_with_warning() -> None:
    bars = daily_bars(A, date(2020, 11, 2), date(2021, 2, 26), "100") + daily_bars(
        B, date(2020, 11, 2), END, "200"
    )

    def buy_late(context: BacktestContext, positions: dict, value: Decimal) -> dict:  # type: ignore[type-arg]
        return {A: 10} if context.today.month >= 5 else {}

    result = run_engine(make_config(), make_market(bars, []))
    assert not result.warnings  # hold_a buys in January while A still prints
    late = run_engine(make_config(), make_market(bars, []), buy_late)
    assert any("no same-day print" in w for w in late.warnings)
    assert late.daily["positions"].to_list()[-1] == 0


def test_unaffordable_buy_is_clamped_to_whole_shares() -> None:
    def buy_everything(context: BacktestContext, positions: dict, value: Decimal) -> dict:  # type: ignore[type-arg]
        return positions or {C: 10**9}

    result = run_engine(make_config(), flat_world(), buy_everything)
    # 1000000 / 400 = 2500 shares exactly, zero costs.
    assert result.daily["cash"].to_list()[-1] == 0.0
    assert result.daily["positions"].to_list()[-1] == 1


def test_write_run_persists_and_never_overwrites(tmp_path: Path) -> None:
    result = run_engine(make_config(), flat_world())
    directory = write_run(result, tmp_path)
    assert (directory / "daily.parquet").exists()
    assert (directory / "events.parquet").exists()
    config = json.loads((directory / "config.json").read_text())
    assert config["name"] == "engine-test"
    meta = json.loads((directory / "meta.json").read_text())
    assert meta["config_hash"] == make_config().config_hash()
    assert meta["git_commit"]
    with pytest.raises(LedgerError, match="never overwritten"):
        write_run(result, tmp_path)
