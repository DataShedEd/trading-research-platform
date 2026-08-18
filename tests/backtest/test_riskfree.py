"""QNT-096: risk-free series loading and window means."""

from datetime import date

import polars as pl
import pytest

from trp.backtest.riskfree import (
    SERIES_NAME,
    RiskFreeError,
    load_risk_free,
    window_mean_rate,
)


def series_frame(rows: list[tuple[date, float]]) -> pl.DataFrame:
    return pl.DataFrame(
        {"date": [r[0] for r in rows], "annual_rate": [r[1] for r in rows]},
        schema={"date": pl.Date, "annual_rate": pl.Float64},
    )


def test_window_mean_is_the_plain_mean_over_the_window() -> None:
    frame = series_frame(
        [
            (date(2021, 1, 4), 0.001),
            (date(2021, 1, 5), 0.002),
            (date(2021, 1, 6), 0.003),
            (date(2022, 1, 4), 0.040),  # outside the window below
        ]
    )
    mean, source = window_mean_rate(frame, date(2021, 1, 1), date(2021, 12, 31))
    assert mean == pytest.approx(0.002)
    assert "3 observations" in source
    assert "approximation" in source  # the convention is stated, not hidden


def test_empty_window_raises() -> None:
    frame = series_frame([(date(2021, 1, 4), 0.001)])
    with pytest.raises(RiskFreeError, match="no observations"):
        window_mean_rate(frame, date(2025, 1, 1), date(2025, 12, 31))


def test_loader_rejects_values_outside_the_rate_band(tmp_path) -> None:  # type: ignore[no-untyped-def]
    directory = tmp_path / SERIES_NAME
    directory.mkdir()
    series_frame([(date(2021, 1, 4), 0.55)]).write_parquet(directory / "series.parquet")
    with pytest.raises(RiskFreeError, match="sanity band"):
        load_risk_free(tmp_path)
