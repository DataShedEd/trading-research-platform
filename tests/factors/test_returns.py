"""Hand-computed returns fixtures. Bars are generated flat on real XLON sessions and
overridden at the dates that matter; every expected VALUE below is hand-derived."""

from datetime import UTC, date, datetime
from decimal import Decimal

import pytest

from trp.canonical.calendars import get_trading_calendar
from trp.domain.corporate_actions import DelistingAction, Dividend, Merger
from trp.domain.identifiers import SecurityId, new_security_id
from trp.domain.prices import DailyBar
from trp.domain.security import DelistingReason
from trp.factors.returns import (
    ReturnBasis,
    ReturnsEngine,
    ReturnStatus,
    WindowSpec,
    shift_months,
)

AS_OF = datetime(2022, 1, 1, tzinfo=UTC)
INGESTED = datetime(2021, 12, 31, tzinfo=UTC)
CAL = get_trading_calendar("XLON")


def daily_bars(
    sid: SecurityId,
    start: date,
    end: date,
    base: str,
    overrides: dict[date, str] | None = None,
    currency: str = "GBX",
) -> list[DailyBar]:
    overrides = overrides or {}
    bars = []
    price = Decimal(base)
    for session in CAL.sessions_between(start, end):
        if session in overrides:
            price = Decimal(overrides[session])
        bars.append(
            DailyBar(
                security_id=sid,
                trade_date=session,
                open=price,
                high=price,
                low=price,
                close=price,
                volume=1000,
                currency=currency,
                source="test",
                ingested_at=INGESTED,
            )
        )
    return bars


def test_shift_months_clamps_month_ends() -> None:
    assert shift_months(date(2021, 3, 31), -1) == date(2021, 2, 28)
    assert shift_months(date(2021, 1, 31), -1) == date(2020, 12, 31)
    assert shift_months(date(2021, 1, 15), -12) == date(2020, 1, 15)


def test_plain_price_move() -> None:
    sid = new_security_id()
    # 1000p all year; steps to 1100p on 1 Dec 2021. 12-0 window ending 31 Dec: +10%.
    bars = daily_bars(
        sid, date(2020, 12, 1), date(2021, 12, 31), "1000", {date(2021, 12, 1): "1100"}
    )
    engine = ReturnsEngine(bars, [], as_of=AS_OF)
    result = engine.window_return(sid, date(2021, 12, 31), WindowSpec(months=12))
    assert result.status is ReturnStatus.OK
    assert result.value == pytest.approx(0.10)


def test_split_produces_no_phantom_return() -> None:
    sid = new_security_id()
    ex = date(2021, 6, 1)
    bars = daily_bars(
        sid, date(2020, 12, 1), date(2021, 12, 31), "1000", {ex: "500", date(2021, 12, 1): "550"}
    )
    from trp.domain.corporate_actions import Split

    split = Split(
        security_id=sid, ex_date=ex, source="t", available_at=AS_OF, new_shares=2, old_shares=1
    )
    engine = ReturnsEngine(bars, [split], as_of=AS_OF)
    result = engine.window_return(sid, date(2021, 12, 31), WindowSpec(months=12))
    # Hand-derived: adjusted start 1000x0.5=500; end 550 -> +10%, split invisible.
    assert result.status is ReturnStatus.OK
    assert result.value == pytest.approx(0.10)


def test_gbp_dividend_on_gbx_bars_is_aligned_not_100x_wrong() -> None:
    sid = new_security_id()
    ex = date(2021, 6, 1)
    bars = daily_bars(sid, date(2020, 12, 1), date(2021, 12, 31), "1000")  # flat 1000p
    dividend = Dividend(
        security_id=sid,
        ex_date=ex,
        source="t",
        available_at=AS_OF,
        amount=Decimal("0.50"),
        currency="GBP",
    )  # 50 PENCE, stated in POUNDS
    engine = ReturnsEngine(bars, [dividend], as_of=AS_OF)
    window = WindowSpec(months=12)
    total = engine.window_return(sid, date(2021, 12, 31), window, ReturnBasis.TOTAL)
    price = engine.window_return(sid, date(2021, 12, 31), window, ReturnBasis.PRICE)
    # Hand-derived under the reinvestment convention: factor = 1 - 50/1000 = 0.95,
    # return = 1000/950 - 1 = 5.263%. Unaligned (50/100000) it would be ~0.05%.
    assert price.value == pytest.approx(0.0)
    assert total.value == pytest.approx(1 / 0.95 - 1)
    assert total.value > 0.02  # the 100x trap, asserted bluntly


def test_special_dividend_flows_through_total_returns() -> None:
    sid = new_security_id()
    bars = daily_bars(sid, date(2020, 12, 1), date(2021, 12, 31), "1000")
    special = Dividend(
        security_id=sid,
        ex_date=date(2021, 6, 1),
        source="t",
        available_at=AS_OF,
        amount=Decimal("100"),
        currency="GBX",
        special=True,
    )
    engine = ReturnsEngine(bars, [special], as_of=AS_OF)
    total = engine.window_return(sid, date(2021, 12, 31), WindowSpec(months=12))
    assert total.value == pytest.approx(1 / 0.9 - 1)  # reinvested: 1000/900 - 1 = 11.1%


def test_twelve_minus_one_skips_the_final_month() -> None:
    sid = new_security_id()
    # Flat 1000p; doubles on 6 Dec 2021 — inside the skip month for end=31 Dec.
    bars = daily_bars(
        sid, date(2020, 11, 1), date(2021, 12, 31), "1000", {date(2021, 12, 6): "2000"}
    )
    engine = ReturnsEngine(bars, [], as_of=AS_OF)
    with_skip = engine.window_return(sid, date(2021, 12, 31), WindowSpec(months=12, skip_months=1))
    without = engine.window_return(sid, date(2021, 12, 31), WindowSpec(months=12))
    assert with_skip.value == pytest.approx(0.0)  # window ends 30 Nov: move excluded
    assert without.value == pytest.approx(1.0)


def test_sparse_series_is_insufficient_not_wrong() -> None:
    sid = new_security_id()
    full = daily_bars(sid, date(2020, 12, 1), date(2021, 12, 31), "1000")
    sparse = full[::3]  # ~33% coverage, below the 60% policy
    engine = ReturnsEngine(sparse, [], as_of=AS_OF)
    result = engine.window_return(sid, date(2021, 12, 31), WindowSpec(months=12))
    assert result.status is ReturnStatus.INSUFFICIENT_DATA
    assert result.value is None


def test_failure_delisting_is_total_loss_not_truncation() -> None:
    sid = new_security_id()
    bars = daily_bars(sid, date(2020, 12, 1), date(2021, 6, 30), "100")  # bars stop mid-window
    failure = DelistingAction(
        security_id=sid,
        ex_date=date(2021, 7, 1),
        source="t",
        available_at=datetime(2021, 7, 1, tzinfo=UTC),
        reason=DelistingReason.FAILURE,
    )
    engine = ReturnsEngine(bars, [failure], as_of=AS_OF)
    result = engine.window_return(sid, date(2021, 12, 31), WindowSpec(months=12))
    assert result.status is ReturnStatus.OK
    assert result.used_delisting_proceeds
    assert result.value == pytest.approx(-1.0)  # -100%, never "flat since June"


def test_acquisition_returns_through_cash_proceeds_with_unit_conversion() -> None:
    sid = new_security_id()
    bars = daily_bars(sid, date(2020, 12, 1), date(2021, 10, 26), "280")  # 280p, bars end
    acquisition = Merger(
        security_id=sid,
        ex_date=date(2021, 10, 27),
        source="t",
        available_at=datetime(2021, 10, 27, tzinfo=UTC),
        cash_amount=Decimal("2.87"),
        cash_currency="GBP",
    )  # 287p in pounds
    engine = ReturnsEngine(bars, [acquisition], as_of=AS_OF)
    result = engine.window_return(sid, date(2021, 12, 31), WindowSpec(months=12))
    assert result.status is ReturnStatus.OK
    assert result.used_delisting_proceeds
    assert result.value == pytest.approx(287 / 280 - 1)  # +2.5%, units aligned exactly


def test_unknown_proceeds_is_typed_not_silent() -> None:
    sid = new_security_id()
    bars = daily_bars(sid, date(2020, 12, 1), date(2021, 6, 30), "100")
    voluntary = DelistingAction(
        security_id=sid,
        ex_date=date(2021, 7, 1),
        source="t",
        available_at=datetime(2021, 7, 1, tzinfo=UTC),
        reason=DelistingReason.VOLUNTARY,
    )
    engine = ReturnsEngine(bars, [voluntary], as_of=AS_OF)
    result = engine.window_return(sid, date(2021, 12, 31), WindowSpec(months=12))
    assert result.status is ReturnStatus.DELISTED_NO_PROCEEDS
    assert result.value is None
