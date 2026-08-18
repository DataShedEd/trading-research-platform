"""QNT-053: hand-computed cost fixtures, stamp asymmetry, impact scaling, pessimistic
defaults, and exact reconciliation of reported costs against ledger debits."""

from datetime import date
from decimal import Decimal

import pytest

from tests.backtest.test_engine import (
    A,
    daily_bars,
    make_config,
    make_market,
    run_engine,
)
from trp.backtest.config import BacktestConfig
from trp.backtest.context import BacktestContext
from trp.backtest.costs import CostModel, Side, no_exemptions
from trp.backtest.engine import MarketData
from trp.domain.identifiers import new_security_id

SID = new_security_id()
DEEP = Decimal("100000000")  # liquid enough that impact is negligible but non-zero


# The shipped defaults, restated explicitly because tests.backtest.test_engine.make_config
# zeroes every cost for accounting tests.
_SHIPPED: dict[str, object] = {
    "commission_bps": Decimal("2"),
    "commission_min": Decimal("500"),
    "spread_bps": Decimal("10"),
    "stamp_duty_bps": Decimal("50"),
    "impact_coefficient_bps": Decimal("25"),
}


def default_model() -> CostModel:
    return CostModel(make_config(name="cost-defaults", **_SHIPPED))


def test_purchase_and_sale_of_the_same_size_are_asymmetric() -> None:
    """Hand-computed on 1,000,000 GBX notional with shipped defaults:
    commission max(200, 500) = 500; half-spread 500; stamp 5000 (buy only);
    impact 25 bps x (1,000,000 / 100,000,000) = 0.025 bps -> 25."""
    model = default_model()
    notional = Decimal("1000000")
    buy = model.cost(SID, Side.BUY, notional, DEEP)
    sell = model.cost(SID, Side.SELL, notional, DEEP)
    assert buy.commission == sell.commission == Decimal("500")
    assert buy.spread == sell.spread == Decimal("500")
    assert buy.impact == sell.impact == Decimal("25")
    assert buy.stamp_duty == Decimal("5000")
    assert sell.stamp_duty == Decimal("0")
    assert buy.total - sell.total == Decimal("5000")  # exactly the stamp duty


def test_minimum_commission_binds_on_small_trades() -> None:
    model = default_model()
    # 10,000 GBX notional: 2 bps = 2, floored to 500.
    assert model.cost(SID, Side.SELL, Decimal("10000"), DEEP).commission == Decimal("500")
    # 10,000,000 GBX notional: 2 bps = 2000 > 500.
    assert model.cost(SID, Side.SELL, Decimal("10000000"), DEEP).commission == Decimal("2000")


def test_stamp_duty_exemption_rule() -> None:
    exempt_model = CostModel(
        make_config(name="cost-defaults", **_SHIPPED), is_stamp_exempt=lambda s: s == SID
    )
    notional = Decimal("1000000")
    assert exempt_model.cost(SID, Side.BUY, notional, DEEP).stamp_duty == Decimal("0")
    other = new_security_id()
    assert exempt_model.cost(other, Side.BUY, notional, DEEP).stamp_duty == Decimal("5000")
    assert no_exemptions(SID) is False  # the default exempts nothing


def test_impact_scales_with_participation() -> None:
    model = default_model()
    median_daily = Decimal("1000000")
    small = model.cost(SID, Side.SELL, Decimal("10000"), median_daily)  # 1% participation
    large = model.cost(SID, Side.SELL, Decimal("500000"), median_daily)  # 50% participation
    # 25 bps x participation x notional: 10000 x 0.0025 x 0.01 = 0.25
    assert small.impact == Decimal("0.25")
    # 500000 x 0.0025 x 0.5 = 625
    assert large.impact == Decimal("625")


def test_no_volume_history_assumes_full_participation() -> None:
    model = default_model()
    notional = Decimal("10000")
    blind = model.cost(SID, Side.SELL, notional, None)
    assert blind.impact == notional * Decimal("0.0025")  # 25 bps at participation 1


def test_shipped_defaults_are_not_below_the_documented_floor() -> None:
    """RESEARCH_METHODOLOGY rule 5: the shipped defaults may only ever get more
    pessimistic. Anyone lowering them must change this test and say why."""
    defaults = BacktestConfig(
        name="floor",
        start=date(2010, 1, 1),
        end=date(2026, 1, 1),
        universe="FTSE100",
        factor="momentum_12_1",
        factor_version=1,
        top_n=20,
        initial_cash=Decimal("1000000"),
    )
    assert defaults.commission_bps >= Decimal("2")
    assert defaults.commission_min >= Decimal("500")  # £5
    assert defaults.spread_bps >= Decimal("10")
    assert defaults.stamp_duty_bps >= Decimal("50")
    assert defaults.impact_coefficient_bps >= Decimal("25")


def test_median_traded_value_is_point_in_time() -> None:
    bars = daily_bars(A, date(2021, 1, 4), date(2021, 6, 30), "100")
    market = MarketData(bars, [], {})
    early = market.median_traded_value(A, date(2021, 2, 1))
    assert early == Decimal("100") * 1000  # flat close x fixture volume
    assert market.median_traded_value(A, date(2020, 12, 1)) is None


def test_costs_reconcile_exactly_with_ledger_debits() -> None:
    config = make_config(
        commission_bps=Decimal("2"),
        commission_min=Decimal("500"),
        spread_bps=Decimal("10"),
        stamp_duty_bps=Decimal("50"),
        impact_coefficient_bps=Decimal("25"),
    )
    bars = daily_bars(A, date(2020, 11, 2), date(2021, 6, 30), "100")

    def churn(context: BacktestContext, positions: dict, value: Decimal) -> dict:  # type: ignore[type-arg]
        return {} if positions else {A: 500}

    result = run_engine(config, make_market(bars, []), churn)
    ledger_costs = sum(Decimal(c) for c in result.events["costs"].to_list())
    reported = result.rebalances["costs"].to_list()
    assert all(c > 0 for c in reported)
    assert float(ledger_costs) == pytest.approx(sum(reported))
    # Gross/net decomposition: final value equals initial cash minus every explicit cost
    # (prices are flat, so trading itself is value-neutral).
    assert result.daily["value"].to_list()[-1] == pytest.approx(1000000.0 - float(ledger_costs))


def test_affordability_clamp_accounts_for_costs() -> None:
    config = make_config(
        commission_bps=Decimal("0"),
        commission_min=Decimal("0"),
        spread_bps=Decimal("0"),
        stamp_duty_bps=Decimal("50"),  # 0.5% on buys
        impact_coefficient_bps=Decimal("0"),
    )
    bars = daily_bars(A, date(2020, 11, 2), date(2021, 6, 30), "100")

    def all_in(context: BacktestContext, positions: dict, value: Decimal) -> dict:  # type: ignore[type-arg]
        return positions or {A: 10**9}

    result = run_engine(config, make_market(bars, []), all_in)
    # floor(1,000,000 / (100 x 1.005)) = 9950 shares; naive floor(cash/price) = 10000
    # would breach cash once stamp duty lands.
    buys = result.events.filter(result.events["kind"] == "buy")
    assert buys["quantity_delta"].to_list() == [9950]
    assert result.daily["cash"].to_list()[-1] >= 0.0
