"""QNT-056: rolling statistics — hand-computed boundaries, backward-looking proof,
minimum observations, day/month equivalence, full-sample consistency."""

from datetime import date, timedelta

import polars as pl
import pytest

from trp.backtest.metrics import (
    MetricsError,
    annualised_volatility,
    beta,
    compute_metrics,
    sharpe_ratio,
)
from trp.backtest.rolling import RollingSpec, rolling_metrics, rolling_report

RETURNS = [0.01, 0.02, 0.03, 0.04]
DATES = [date(2021, 3, 1) + timedelta(days=i) for i in range(4)]
FRAME = pl.DataFrame({"date": DATES, "ret": RETURNS})


def test_spec_requires_exactly_one_length() -> None:
    with pytest.raises(MetricsError):
        RollingSpec()
    with pytest.raises(MetricsError):
        RollingSpec(trading_days=5, calendar_months=1)
    with pytest.raises(MetricsError):
        RollingSpec(trading_days=5, min_observations=1)


def test_hand_computed_window_boundaries() -> None:
    spec = RollingSpec(trading_days=2, min_observations=2)
    rolled = rolling_metrics(FRAME, spec, periods_per_year=252)
    assert rolled["ret"][0] is None  # one observation only: below the minimum
    assert rolled["ret"][1] == pytest.approx(1.01 * 1.02 - 1)
    assert rolled["ret"][3] == pytest.approx(1.03 * 1.04 - 1)  # last two returns only
    # Same conventions as the full-sample implementations, by construction:
    assert rolled["volatility"][3] == pytest.approx(annualised_volatility([0.03, 0.04], 252))
    assert rolled["sharpe"][3] == pytest.approx(sharpe_ratio([0.03, 0.04], 252, 0.0))


def test_windows_are_strictly_backward_looking() -> None:
    """Appending later observations must not change earlier rows — a centred window
    would fail this immediately."""
    spec = RollingSpec(trading_days=2, min_observations=2)
    short = rolling_metrics(FRAME.head(3), spec)
    extended = rolling_metrics(FRAME, spec)
    assert extended.head(3).equals(short)


def test_minimum_observations_yield_nulls_not_partial_statistics() -> None:
    spec = RollingSpec(trading_days=10, min_observations=4)
    rolled = rolling_metrics(FRAME, spec)
    assert rolled["ret"].to_list()[:3] == [None, None, None]
    assert rolled["observations"].to_list() == [1, 2, 3, 4]
    assert rolled["ret"][3] is not None


def test_trading_day_and_calendar_month_windows_agree_where_they_coincide() -> None:
    # March 2021 has 31 consecutive fixture days; at 31 March a 1-calendar-month window
    # (dates after 28 Feb) and a 31-trading-day window hold identical observations.
    dates = [date(2021, 3, 1) + timedelta(days=i) for i in range(31)]
    frame = pl.DataFrame({"date": dates, "ret": [0.001 * (i % 5) for i in range(31)]})
    by_days = rolling_metrics(frame, RollingSpec(trading_days=31, min_observations=5))
    by_months = rolling_metrics(frame, RollingSpec(calendar_months=1, min_observations=5))
    for column in ("ret", "volatility", "sharpe"):
        assert by_days[column][-1] == pytest.approx(by_months[column][-1])


def test_whole_period_window_matches_full_sample_metrics() -> None:
    equity_values = [100.0]
    for r in RETURNS:
        equity_values.append(equity_values[-1] * (1 + r))
    equity = pl.DataFrame({"date": [DATES[0] - timedelta(days=1), *DATES], "value": equity_values})
    full = compute_metrics(equity, periods_per_year=252)
    rolled = rolling_metrics(FRAME, RollingSpec(trading_days=4, min_observations=4))
    assert rolled["ret"][-1] == pytest.approx(full.total_return)
    assert rolled["volatility"][-1] == pytest.approx(full.annualised_volatility)
    assert rolled["sharpe"][-1] == pytest.approx(full.sharpe)


def test_rolling_beta_matches_full_sample_beta_over_the_whole_window() -> None:
    bench = pl.DataFrame({"date": DATES, "ret": [0.02, -0.04, 0.04, 0.02]})
    rolled = rolling_metrics(
        FRAME, RollingSpec(trading_days=4, min_observations=4), benchmark_returns=bench
    )
    assert rolled["beta"][-1] == pytest.approx(beta(FRAME, bench))


def test_misaligned_benchmark_raises() -> None:
    bench = pl.DataFrame({"date": DATES[:3], "ret": [0.0, 0.0, 0.0]})
    with pytest.raises(MetricsError, match="align"):
        rolling_metrics(FRAME, RollingSpec(trading_days=2), benchmark_returns=bench)


def test_report_carries_every_configured_window_together() -> None:
    report = rolling_report(
        FRAME,
        (
            RollingSpec(trading_days=2, min_observations=2),
            RollingSpec(trading_days=3, min_observations=3),
        ),
    )
    assert set(report["window"].unique()) == {"2d", "3d"}
    assert report.height == 2 * FRAME.height
    with pytest.raises(MetricsError, match="at least one"):
        rolling_report(FRAME, ())
