"""Rolling statistics (QNT-056): regime dependence as a reported output.

Windows are strictly BACKWARD-looking — the value at date t uses observations at or
before t only — and specified in trading days or calendar months. Metric formulas are
the QNT-054 implementations (``compound``, ``annualised_volatility``, ``sharpe_ratio``,
covariance beta), applied per window, so a rolling Sharpe and the full-sample Sharpe
cannot diverge in convention.

Windows with fewer than ``min_observations`` returns yield nulls, never a statistic from
a partial window. Rolling beta demands a benchmark aligned to EXACTLY the strategy's
dates and raises otherwise — misalignment in a rolling context produces plausible values
that are quietly wrong.

The full set of windows configured for a run is persisted together (``rolling.parquet``,
tagged with the window spec and annualisation), so a favourable window is visibly a
selection from the set rather than the only thing reported.
"""

from dataclasses import dataclass
from datetime import date

import polars as pl

from trp.backtest.metrics import (
    MetricsError,
    _require_columns,
    annualised_volatility,
    compound,
    sharpe_ratio,
)
from trp.factors.returns import shift_months


@dataclass(frozen=True)
class RollingSpec:
    """Exactly one of ``trading_days`` or ``calendar_months`` sets the window length."""

    trading_days: int | None = None
    calendar_months: int | None = None
    min_observations: int = 20

    def __post_init__(self) -> None:
        if (self.trading_days is None) == (self.calendar_months is None):
            raise MetricsError("specify exactly one of trading_days or calendar_months")
        if self.min_observations < 2:
            raise MetricsError("min_observations must be at least 2")

    @property
    def label(self) -> str:
        if self.trading_days is not None:
            return f"{self.trading_days}d"
        return f"{self.calendar_months}m"


def rolling_metrics(
    returns: pl.DataFrame,
    spec: RollingSpec,
    *,
    periods_per_year: int = 252,
    risk_free_rate: float = 0.0,
    benchmark_returns: pl.DataFrame | None = None,
) -> pl.DataFrame:
    """One row per date: window total return, annualised volatility, Sharpe, and (with a
    benchmark) beta. Columns are null until the window holds ``min_observations``."""
    _require_columns(returns, {"date", "ret"}, "returns")
    if not returns["date"].is_sorted():
        raise MetricsError("returns must be date-sorted")
    bench: list[float] | None = None
    if benchmark_returns is not None:
        if benchmark_returns["date"].to_list() != returns["date"].to_list():
            raise MetricsError(
                "benchmark dates do not exactly match strategy dates — align() first"
            )
        bench = [float(r) for r in benchmark_returns["ret"]]

    dates: list[date] = returns["date"].to_list()
    values = [float(r) for r in returns["ret"]]
    rows: list[dict[str, object]] = []
    start_index = 0
    for i, day in enumerate(dates):
        if spec.trading_days is not None:
            start_index = max(0, i + 1 - spec.trading_days)
        else:
            assert spec.calendar_months is not None
            cutoff = shift_months(day, -spec.calendar_months)
            while dates[start_index] <= cutoff:
                start_index += 1
        window = values[start_index : i + 1]
        row: dict[str, object] = {
            "date": day,
            "window": spec.label,
            "observations": len(window),
            "ret": None,
            "volatility": None,
            "sharpe": None,
            "beta": None,
        }
        if len(window) >= spec.min_observations:
            row["ret"] = compound(window)
            row["volatility"] = annualised_volatility(window, periods_per_year)
            row["sharpe"] = sharpe_ratio(window, periods_per_year, risk_free_rate)
            if bench is not None:
                row["beta"] = _beta(window, bench[start_index : i + 1])
        rows.append(row)
    return pl.DataFrame(
        rows,
        schema={
            "date": pl.Date,
            "window": pl.Utf8,
            "observations": pl.Int64,
            "ret": pl.Float64,
            "volatility": pl.Float64,
            "sharpe": pl.Float64,
            "beta": pl.Float64,
        },
    )


def _beta(a: list[float], b: list[float]) -> float | None:
    n = len(a)
    mean_a, mean_b = sum(a) / n, sum(b) / n
    covariance = sum((x - mean_a) * (y - mean_b) for x, y in zip(a, b, strict=True)) / (n - 1)
    variance = sum((y - mean_b) ** 2 for y in b) / (n - 1)
    if variance == 0:
        return None
    return covariance / variance


def rolling_report(
    returns: pl.DataFrame,
    specs: tuple[RollingSpec, ...],
    *,
    periods_per_year: int = 252,
    risk_free_rate: float = 0.0,
    benchmark_returns: pl.DataFrame | None = None,
) -> pl.DataFrame:
    """All configured windows in ONE frame — the anti-cherry-picking shape."""
    if not specs:
        raise MetricsError("at least one rolling window must be configured")
    frames = [
        rolling_metrics(
            returns,
            spec,
            periods_per_year=periods_per_year,
            risk_free_rate=risk_free_rate,
            benchmark_returns=benchmark_returns,
        )
        for spec in specs
    ]
    return pl.concat(frames)
