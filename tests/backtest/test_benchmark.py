"""QNT-055: total-return construction, relative measures, suitability, alignment."""

from dataclasses import replace
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal

import polars as pl
import pytest

from tests.backtest.test_config import make_config
from trp.backtest.benchmark import (
    BenchmarkError,
    BenchmarkSeries,
    align,
    check_suitability,
    relative_metrics,
    total_return_series,
)
from trp.backtest.metrics import MetricsError

AS_OF = datetime(2021, 12, 31, tzinfo=UTC)


def bar_frame(rows: list[tuple[date, str]]) -> pl.DataFrame:
    return pl.DataFrame(
        {"trade_date": [r[0] for r in rows], "close": [Decimal(r[1]) for r in rows]}
    )


def dividend_frame(rows: list[tuple[date, str, str, datetime]]) -> pl.DataFrame:
    return pl.DataFrame(
        {
            "ex_date": [r[0] for r in rows],
            "amount": [Decimal(r[1]) for r in rows],
            "currency": [r[2] for r in rows],
            "available_at": [r[3] for r in rows],
        }
    )


NO_DIVIDENDS = dividend_frame([(date(2021, 1, 1), "1", "GBP", AS_OF)]).clear()


def test_total_return_exceeds_price_return_across_a_dividend() -> None:
    days = [date(2021, 3, d) for d in (1, 2, 3)]
    bars = bar_frame([(days[0], "1000"), (days[1], "1000"), (days[2], "1000")])
    dividends = dividend_frame([(days[1], "0.50", "GBP", AS_OF)])  # 50p, stated in pounds
    returns = total_return_series(bars, dividends, as_of=AS_OF)
    assert returns["ret"].to_list() == [pytest.approx(0.05), 0.0]  # price-only would be 0
    price_only = total_return_series(bars, NO_DIVIDENDS, as_of=AS_OF)
    assert sum(returns["ret"]) > sum(price_only["ret"])


def test_unit_flip_refuses_to_compute() -> None:
    bars = bar_frame([(date(2021, 3, 1), "1000"), (date(2021, 3, 2), "10")])
    with pytest.raises(BenchmarkError, match="unit flip"):
        total_return_series(bars, NO_DIVIDENDS, as_of=AS_OF)


def series(dates: list[date], rets: list[float], **overrides: str) -> BenchmarkSeries:
    values = {
        "name": "test-bench",
        "universe": "FTSE100",
        "currency": "GBX",
        "kind": "fixture",
        "source": "test",
    }
    values.update(overrides)
    return BenchmarkSeries(
        returns=pl.DataFrame({"date": dates, "ret": rets}),
        **values,  # type: ignore[arg-type]
    )


DATES = [date(2021, 1, d) for d in (4, 5, 6)]


def test_relative_metrics_hand_computed() -> None:
    # Active returns 0, 0.01, 0.02: mean 0.01, sample stdev 0.01. With 3 periods/year:
    # TE = 0.01 * sqrt(3); IR = 0.01 * 3 / TE = sqrt(3); excess CAGR over one "year"
    # = 1.061106 / 1.030301 - 1.
    strategy = pl.DataFrame({"date": DATES, "ret": [0.01, 0.02, 0.03]})
    benchmark = series(DATES, [0.01, 0.01, 0.01])
    record = relative_metrics(strategy, benchmark, periods_per_year=3)
    assert record.tracking_error == pytest.approx(0.01 * 3**0.5)
    assert record.information_ratio == pytest.approx(3**0.5)
    assert record.strategy_total_return == pytest.approx(1.01 * 1.02 * 1.03 - 1)
    assert record.benchmark_total_return == pytest.approx(1.01**3 - 1)
    assert record.excess_cagr == pytest.approx(1.01 * 1.02 * 1.03 / 1.01**3 - 1)


def test_relative_metrics_requires_exact_alignment() -> None:
    strategy = pl.DataFrame({"date": DATES[:2], "ret": [0.01, 0.02]})
    with pytest.raises(MetricsError, match="align"):
        relative_metrics(strategy, series(DATES, [0.0, 0.0, 0.0]), periods_per_year=3)


def test_align_reports_every_dropped_date() -> None:
    strategy = pl.DataFrame({"date": DATES, "ret": [0.01, 0.02, 0.03]})
    benchmark = pl.DataFrame({"date": [*DATES[1:], date(2021, 1, 7)], "ret": [0.0, 0.0, 0.0]})
    a, b, dropped = align(strategy, benchmark)
    assert a["date"].to_list() == b["date"].to_list() == DATES[1:]
    assert dropped == [DATES[0], date(2021, 1, 7)]  # both sides' orphans, no silence


def test_suitability_check_passes_and_fails() -> None:
    config = make_config()  # FTSE100 strategy, 2010..2026
    dates = [config.start + timedelta(days=i) for i in range(3)]
    good = series([*dates[:1], config.end], [0.0, 0.0])
    assert check_suitability(config, good, dates) == []
    wrong_universe = replace(good, universe="FTSE250")
    assert any("FTSE250" in w for w in check_suitability(config, wrong_universe, dates))
    wrong_currency = replace(good, currency="USD")
    assert any("USD" in w for w in check_suitability(config, wrong_currency, dates))
    short = series(dates, [0.0, 0.0, 0.0])  # ends long before the strategy does
    assert any("covers" in w for w in check_suitability(config, short, [*dates, config.end]))
