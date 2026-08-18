"""QNT-054: every metric against hand-computed fixtures derived independently on paper."""

from datetime import date
from decimal import Decimal
from pathlib import Path

import polars as pl
import pytest

from trp.backtest.metrics import (
    MetricsError,
    beta,
    compute_metrics,
    daily_returns,
    max_drawdown,
    position_hit_rate,
    write_metrics,
)
from trp.backtest.portfolio import Portfolio
from trp.domain.identifiers import new_security_id


def equity_frame(values: list[float], start_year: int = 2021) -> pl.DataFrame:
    dates = [date(start_year, 1, d + 1) for d in range(len(values))]
    return pl.DataFrame({"date": dates, "value": values})


# Hand-worked fixture: returns +10%, -10%, +10%, 0%, +20% with periods_per_year=5.
# mean 0.06; sample stdev sqrt(0.052/4) = 0.11401754; vol = stdev * sqrt(5) = 0.25495098;
# Sharpe (rf=0) = 0.06/0.11401754 * sqrt(5) = 1.17669681;
# downside RMS = sqrt(0.01/5) = 0.04472136 -> Sortino = 0.06/0.04472136 * sqrt(5) = 3.0;
# max drawdown 110 -> 99 = -10%; total = CAGR (exactly one year) = 0.3068;
# Calmar = 0.3068/0.1 = 3.068; hit rate 3/5.
HAND = equity_frame([100.0, 110.0, 99.0, 108.9, 108.9, 130.68])


def hand_metrics():  # type: ignore[no-untyped-def]
    return compute_metrics(HAND, periods_per_year=5, risk_free_rate=0.0)


def test_total_return_and_cagr() -> None:
    record = hand_metrics()
    assert record.total_return == pytest.approx(0.3068)
    assert record.cagr == pytest.approx(0.3068)  # exactly one "year" of periods
    assert record.flags == ()


def test_volatility_and_sharpe() -> None:
    record = hand_metrics()
    assert record.annualised_volatility == pytest.approx(0.25495098)
    assert record.sharpe == pytest.approx(1.17669681)


def test_sortino_hand_case() -> None:
    assert hand_metrics().sortino == pytest.approx(3.0)


def test_max_drawdown_and_calmar() -> None:
    record = hand_metrics()
    assert record.max_drawdown == pytest.approx(-0.1)
    assert record.max_drawdown_trough == date(2021, 1, 3)
    assert record.calmar == pytest.approx(3.068)


def test_hit_rate_periods() -> None:
    assert hand_metrics().hit_rate_periods == pytest.approx(3 / 5)


def test_annual_returns_compound_to_total_return() -> None:
    curve = pl.DataFrame(
        {
            "date": [date(2020, 12, 31), date(2021, 6, 30), date(2021, 12, 31), date(2022, 6, 30)],
            "value": [100.0, 120.0, 108.0, 135.0],
        }
    )
    record = compute_metrics(curve, periods_per_year=2)
    assert record.annual_returns[2021] == pytest.approx(0.08)  # 100 -> 108
    assert record.annual_returns[2022] == pytest.approx(0.25)  # 108 -> 135
    compounded = 1.0
    for annual in record.annual_returns.values():
        compounded *= 1 + annual
    assert compounded - 1 == pytest.approx(record.total_return)


def test_risk_free_rate_lowers_sharpe_and_is_recorded() -> None:
    with_rf = compute_metrics(
        HAND, periods_per_year=5, risk_free_rate=0.05, risk_free_source="test fixture"
    )
    without = hand_metrics()
    assert with_rf.sharpe is not None and without.sharpe is not None
    assert with_rf.sharpe < without.sharpe
    assert with_rf.risk_free_rate == 0.05
    assert with_rf.risk_free_source == "test fixture"
    assert with_rf.minimum_acceptable_return == 0.05  # MAR defaults to the risk-free rate


def test_within_month_trough_is_not_understated() -> None:
    daily = equity_frame([100.0, 80.0, 105.0])
    drawdown, trough = max_drawdown(daily)
    assert drawdown == pytest.approx(-0.2)
    assert trough == date(2021, 1, 2)
    month_ends = equity_frame([100.0, 105.0])  # what month-end sampling would see
    assert max_drawdown(month_ends)[0] == 0.0  # the understatement the ticket warns about


def test_short_sample_is_flagged_as_extrapolation() -> None:
    record = compute_metrics(equity_frame([100.0, 101.0, 102.0]), periods_per_year=252)
    assert any(flag.startswith("short_sample") for flag in record.flags)
    assert record.cagr is not None  # still reported, but flagged


def test_constant_equity_curve_degenerates_explicitly() -> None:
    record = compute_metrics(equity_frame([100.0] * 6), periods_per_year=5)
    assert record.sharpe is None
    assert record.sortino is None
    assert record.annualised_volatility == 0.0
    assert record.max_drawdown == 0.0
    assert record.calmar is None
    assert any(flag.startswith("zero_volatility") for flag in record.flags)
    assert any(flag.startswith("no_drawdown") for flag in record.flags)


def test_all_negative_path_reports_honest_numbers() -> None:
    curve = equity_frame([100.0, 90.0, 80.0, 70.0, 65.0, 60.0])
    record = compute_metrics(curve, periods_per_year=5)
    assert record.cagr == pytest.approx(-0.4)
    assert record.max_drawdown == pytest.approx(-0.4)
    assert record.calmar is not None and record.calmar < 0
    assert record.hit_rate_periods == 0.0


def test_beta_hand_case() -> None:
    dates = [date(2021, 1, i) for i in (1, 2, 3)]
    a = pl.DataFrame({"date": dates, "ret": [0.02, -0.01, 0.03]})
    b = pl.DataFrame({"date": dates, "ret": [0.02, -0.04, 0.04]})
    assert beta(a, b) == pytest.approx(0.5)


def test_beta_rejects_misaligned_series() -> None:
    a = pl.DataFrame({"date": [date(2021, 1, 1), date(2021, 1, 2)], "ret": [0.01, 0.02]})
    b = pl.DataFrame(
        {"date": [date(2021, 1, 1), date(2021, 1, 2), date(2021, 1, 3)], "ret": [0.01, 0.02, 0.03]}
    )
    with pytest.raises(MetricsError, match="dates differ"):
        beta(a, b)
    flat = pl.DataFrame({"date": a["date"], "ret": [0.01, 0.01]})
    with pytest.raises(MetricsError, match="variance is zero"):
        beta(a, flat)


def test_returns_require_sorted_dates_and_columns() -> None:
    with pytest.raises(MetricsError, match="date-sorted"):
        daily_returns(
            pl.DataFrame({"date": [date(2021, 1, 2), date(2021, 1, 1)], "value": [1.0, 2.0]})
        )
    with pytest.raises(MetricsError, match="missing columns"):
        daily_returns(pl.DataFrame({"date": [date(2021, 1, 1)]}))
    with pytest.raises(MetricsError, match="two observations"):
        daily_returns(pl.DataFrame({"date": [date(2021, 1, 1)], "value": [1.0]}))


def events_frame(portfolio: Portfolio) -> pl.DataFrame:
    return pl.DataFrame([e.model_dump(mode="json") for e in portfolio.events()])


def test_position_hit_rate_counts_round_trips() -> None:
    a, b, c, d = (new_security_id() for _ in range(4))
    portfolio = Portfolio(Decimal("100000"), date(2021, 1, 4))
    # A: clean winner. B: loses on price, saved by a dividend. C: written off. D: open.
    portfolio.buy(a, 10, Decimal("100"), Decimal(0), date(2021, 1, 4))
    portfolio.sell(a, 10, Decimal("110"), Decimal(0), date(2021, 2, 1))
    portfolio.buy(b, 10, Decimal("100"), Decimal(0), date(2021, 1, 4))
    portfolio.credit_dividend(b, Decimal("5"), date(2021, 1, 20), special=False)
    portfolio.sell(b, 10, Decimal("96"), Decimal(0), date(2021, 2, 1))
    portfolio.buy(c, 10, Decimal("100"), Decimal(0), date(2021, 1, 4))
    portfolio.resolve_delisting(c, None, date(2021, 3, 1), note="failure")
    portfolio.buy(d, 10, Decimal("100"), Decimal(0), date(2021, 1, 4))
    # A +100, B -1000+50+960 = +10, C -1000; D open and excluded -> 2 of 3.
    assert position_hit_rate(events_frame(portfolio)) == pytest.approx(2 / 3)


def test_write_metrics_never_overwrites(tmp_path: Path) -> None:
    record = hand_metrics()
    target = write_metrics(record, tmp_path)
    assert target.exists()
    assert '"cagr"' in target.read_text()
    with pytest.raises(MetricsError, match="immutable"):
        write_metrics(record, tmp_path)
