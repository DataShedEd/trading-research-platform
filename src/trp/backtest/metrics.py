"""Performance metrics (QNT-054): one canonical return series, explicit conventions.

Every metric derives from ONE daily simple-return series computed from the equity curve,
so no two metrics can disagree about what the returns were. Conventions are parameters
recorded in the ``MetricsRecord``, never constants hidden in formulas:

- ``periods_per_year`` — the annualisation factor (252 for daily equity curves).
- ``risk_free_rate`` — ANNUAL rate, converted geometrically to per-period; its source is
  recorded as text alongside the number.
- Sharpe = mean excess per-period return / sample stdev of per-period returns, annualised
  by sqrt(periods_per_year).
- Sortino's downside deviation is the root mean square of returns below the per-period
  minimum acceptable return (full-sample denominator, the standard convention), with the
  MAR defaulting to the risk-free rate and recorded explicitly.
- Maximum drawdown runs over the FULL-frequency equity curve (never resampled), and
  Calmar = CAGR / |max drawdown| over the same period.
- Hit rate has two documented definitions reported separately: proportion of positive
  periods, and proportion of profitable round-trip positions from the trade log (a
  position is one security's full buy-to-flat cycle; proceeds include dividends and
  delisting cash received during it).

Degenerate inputs return None with a reason in ``flags`` rather than a division error or a
misleading number: fewer than one year of data flags every annualised figure as an
extrapolation; zero volatility yields Sharpe/Sortino of None; an all-negative equity path
still reports its (negative) CAGR and full drawdown.
"""

import json
import math
from dataclasses import asdict, dataclass, field
from datetime import date
from pathlib import Path

import polars as pl


class MetricsError(Exception):
    pass


@dataclass(frozen=True)
class MetricsRecord:
    start: date
    end: date
    periods: int
    periods_per_year: int
    risk_free_rate: float
    risk_free_source: str
    minimum_acceptable_return: float
    total_return: float
    cagr: float | None
    annualised_volatility: float | None
    sharpe: float | None
    sortino: float | None
    max_drawdown: float
    max_drawdown_trough: date
    calmar: float | None
    hit_rate_periods: float | None
    hit_rate_positions: float | None
    annual_returns: dict[int, float] = field(default_factory=dict)
    flags: tuple[str, ...] = ()

    def to_json(self) -> str:
        payload = asdict(self)
        payload["start"] = self.start.isoformat()
        payload["end"] = self.end.isoformat()
        payload["max_drawdown_trough"] = self.max_drawdown_trough.isoformat()
        payload["annual_returns"] = {str(k): v for k, v in self.annual_returns.items()}
        payload["flags"] = list(self.flags)
        return json.dumps(payload, indent=2)


def compound(returns: list[float]) -> float:
    """Total return from compounding per-period simple returns."""
    total = 1.0
    for r in returns:
        total *= 1 + r
    return total - 1


def annualised_volatility(returns: list[float], periods_per_year: int) -> float | None:
    """Sample stdev of per-period returns, annualised by sqrt(periods_per_year).
    None below two observations."""
    n = len(returns)
    if n < 2:
        return None
    mean = sum(returns) / n
    variance = sum((r - mean) ** 2 for r in returns) / (n - 1)
    return math.sqrt(variance) * math.sqrt(periods_per_year)


def sharpe_ratio(
    returns: list[float], periods_per_year: int, risk_free_rate: float
) -> float | None:
    """Mean excess per-period return over sample stdev, annualised. The ONE Sharpe
    implementation — full-sample and rolling both call it, so they cannot diverge.
    None for zero volatility or fewer than two observations."""
    n = len(returns)
    if n < 2:
        return None
    per_period_rf = (1 + risk_free_rate) ** (1 / periods_per_year) - 1
    mean = sum(returns) / n
    variance = sum((r - mean) ** 2 for r in returns) / (n - 1)
    stdev = math.sqrt(variance)
    if stdev == 0:
        return None
    return float((mean - per_period_rf) / stdev * math.sqrt(periods_per_year))


def daily_returns(equity: pl.DataFrame) -> pl.DataFrame:
    """The canonical (date, ret) series: simple returns of consecutive equity values."""
    _require_columns(equity, {"date", "value"}, "equity curve")
    if equity.height < 2:
        raise MetricsError("equity curve needs at least two observations")
    if not equity["date"].is_sorted():
        raise MetricsError("equity curve must be date-sorted")
    return equity.select(
        pl.col("date"),
        (pl.col("value") / pl.col("value").shift(1) - 1).alias("ret"),
    ).drop_nulls()


def max_drawdown(equity: pl.DataFrame) -> tuple[float, date]:
    """Deepest peak-to-trough decline over the FULL-frequency curve and its trough date."""
    _require_columns(equity, {"date", "value"}, "equity curve")
    peak = float("-inf")
    worst = 0.0
    trough = equity["date"][0]
    for day, value in zip(equity["date"], equity["value"], strict=True):
        value = float(value)
        peak = max(peak, value)
        drawdown = value / peak - 1
        if drawdown < worst:
            worst = drawdown
            trough = day
    return worst, trough


def beta(returns: pl.DataFrame, benchmark_returns: pl.DataFrame) -> float:
    """Covariance/variance beta on date-joined series of the SAME periodicity.

    Mismatched or partially overlapping dates raise rather than silently aligning."""
    _require_columns(returns, {"date", "ret"}, "returns")
    _require_columns(benchmark_returns, {"date", "ret"}, "benchmark returns")
    if set(returns["date"]) != set(benchmark_returns["date"]):
        missing = set(returns["date"]).symmetric_difference(benchmark_returns["date"])
        raise MetricsError(
            f"returns and benchmark dates differ on {len(missing)} dates — "
            "align periodicity and range explicitly before computing beta"
        )
    joined = returns.join(benchmark_returns, on="date", suffix="_bench").sort("date")
    a = joined["ret"].to_list()
    b = joined["ret_bench"].to_list()
    n = len(a)
    if n < 2:
        raise MetricsError("beta needs at least two overlapping periods")
    mean_a, mean_b = sum(a) / n, sum(b) / n
    covariance = sum((x - mean_a) * (y - mean_b) for x, y in zip(a, b, strict=True)) / (n - 1)
    variance = sum((y - mean_b) ** 2 for y in b) / (n - 1)
    if variance == 0:
        raise MetricsError("benchmark variance is zero — beta is undefined")
    return float(covariance / variance)


def compute_metrics(
    equity: pl.DataFrame,
    events: pl.DataFrame | None = None,
    *,
    periods_per_year: int = 252,
    risk_free_rate: float = 0.0,
    risk_free_source: str = "assumed zero",
    minimum_acceptable_return: float | None = None,
) -> MetricsRecord:
    returns_frame = daily_returns(equity)
    returns = [float(r) for r in returns_frame["ret"]]
    dates = returns_frame["date"].to_list()
    start: date = equity["date"][0]
    end: date = equity["date"][-1]
    n = len(returns)
    flags: list[str] = []

    first = float(equity["value"][0])
    last = float(equity["value"][-1])
    if first <= 0:
        raise MetricsError("equity curve must start positive")
    total_return = last / first - 1

    years = n / periods_per_year
    if years < 1.0:
        flags.append("short_sample: under one year — annualised figures are extrapolations")

    cagr: float | None = None
    if last > 0 and years > 0:
        cagr = (last / first) ** (1 / years) - 1
    elif last <= 0:
        flags.append("total_loss: equity reached zero — CAGR undefined")

    mar = minimum_acceptable_return if minimum_acceptable_return is not None else risk_free_rate
    per_period_mar = (1 + mar) ** (1 / periods_per_year) - 1

    mean = sum(returns) / n
    volatility = annualised_volatility(returns, periods_per_year)
    sharpe = sharpe_ratio(returns, periods_per_year, risk_free_rate)
    if volatility == 0:
        flags.append("zero_volatility: Sharpe and Sortino undefined")

    sortino: float | None = None
    downside = [min(0.0, r - per_period_mar) for r in returns]
    downside_deviation = math.sqrt(sum(d * d for d in downside) / n)
    if downside_deviation > 0:
        sortino = (mean - per_period_mar) / downside_deviation * math.sqrt(periods_per_year)

    drawdown, trough = max_drawdown(equity)
    calmar: float | None = None
    if cagr is not None and drawdown < 0:
        calmar = cagr / abs(drawdown)
    elif drawdown == 0:
        flags.append("no_drawdown: Calmar undefined")

    hit_periods = sum(1 for r in returns if r > 0) / n if n else None

    annual: dict[int, float] = {}
    compounding: dict[int, float] = {}
    for day, r in zip(dates, returns, strict=True):
        compounding[day.year] = compounding.get(day.year, 1.0) * (1 + r)
    for year, growth in sorted(compounding.items()):
        annual[year] = growth - 1

    return MetricsRecord(
        start=start,
        end=end,
        periods=n,
        periods_per_year=periods_per_year,
        risk_free_rate=risk_free_rate,
        risk_free_source=risk_free_source,
        minimum_acceptable_return=mar,
        total_return=total_return,
        cagr=cagr,
        annualised_volatility=volatility,
        sharpe=sharpe,
        sortino=sortino,
        max_drawdown=drawdown,
        max_drawdown_trough=trough,
        calmar=calmar,
        hit_rate_periods=hit_periods,
        hit_rate_positions=position_hit_rate(events) if events is not None else None,
        annual_returns=annual,
        flags=tuple(flags),
    )


def position_hit_rate(events: pl.DataFrame) -> float | None:
    """Proportion of profitable round-trip positions from the ledger event log.

    A round trip is one security's buy-to-flat cycle; cash received while it was open
    (sales, dividends, delisting proceeds) counts toward its outcome. Open positions at
    the end of the run are excluded — their outcome is not yet known."""
    if events.height == 0:
        return None
    outcomes: list[bool] = []
    open_flows: dict[str, float] = {}
    open_quantity: dict[str, int] = {}
    for event in events.sort("on").iter_rows(named=True):
        security_id = event["security_id"]
        if security_id is None:
            continue
        quantity = int(event["quantity_delta"])
        flow = float(event["cash_delta"])
        if security_id not in open_quantity and quantity <= 0:
            continue  # cash-only event for a never-held or already-closed name
        open_flows[security_id] = open_flows.get(security_id, 0.0) + flow
        open_quantity[security_id] = open_quantity.get(security_id, 0) + quantity
        if open_quantity[security_id] == 0:
            outcomes.append(open_flows[security_id] > 0)
            del open_quantity[security_id]
            del open_flows[security_id]
    return sum(outcomes) / len(outcomes) if outcomes else None


def write_metrics(record: MetricsRecord, directory: Path) -> Path:
    target = directory / "metrics.json"
    if target.exists():
        raise MetricsError(f"{target} exists; metrics are part of the immutable run record")
    target.write_text(record.to_json())
    return target


def _require_columns(frame: pl.DataFrame, required: set[str], label: str) -> None:
    missing = required - set(frame.columns)
    if missing:
        raise MetricsError(f"{label} is missing columns {sorted(missing)}")
