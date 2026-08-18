"""Total-return benchmarks and relative performance (QNT-055).

The benchmark for FTSE 100 strategies is the iShares Core FTSE 100 UCITS ETF (ISF.LSE,
distributing, GBX, history from May 2000) with its own dividends REINVESTED on their
ex-dates — a genuine total-return series (RESEARCH_METHODOLOGY rule 6: a price index
omits dividends worth several percent a year, flattering any strategy compared against
it). An ETF rather than the licensed index because it is investable, in the right
currency, carries realistic fund costs, and its data flows through the same raw-first
EODHD machinery as everything else. The accumulating share class (CUKX.LSE, from
Sept 2010) does the reinvestment for us and serves as an independent cross-check in the
gate suite.

Construction is point-in-time: the series at date t uses closes on or before t and only
dividends knowable at t (``available_at``), so later backfills cannot change history —
asserted in the timetravel suite.

Alignment is explicit everywhere: relative metrics demand identical date sets and raise
otherwise; ``align()`` is the one documented reconciliation step, and it reports every
dropped date so nothing leaves the comparison silently.
"""

import json
from dataclasses import dataclass
from datetime import UTC, date, datetime, time
from decimal import Decimal
from pathlib import Path

import polars as pl

from trp.backtest.config import BacktestConfig
from trp.backtest.metrics import MetricsError, _require_columns
from trp.domain.reference import default_reference_data

BENCHMARKS = {
    "isf-xlon-tr": {
        "symbol": "ISF:XLON",
        "universe": "FTSE100",
        "currency": "GBX",
        "kind": "etf_total_return (distributing share class, dividends reinvested at "
        "ex-date close)",
        "source": "EODHD ISF.LSE bars + dividends; see data/canonical/benchmarks/",
    },
    "cukx-xlon-acc": {
        "symbol": "CUKX:XLON",
        "universe": "FTSE100",
        "currency": "GBX",
        "kind": "etf_total_return (accumulating share class, reinvestment internal to the fund)",
        "source": "EODHD CUKX.LSE bars; cross-check series",
    },
}


class BenchmarkError(Exception):
    pass


@dataclass(frozen=True)
class BenchmarkSeries:
    name: str
    universe: str
    currency: str
    kind: str
    source: str
    returns: pl.DataFrame  # date, ret (daily total return)

    @property
    def start(self) -> date:
        return self.returns["date"][0]  # type: ignore[no-any-return]

    @property
    def end(self) -> date:
        return self.returns["date"][-1]  # type: ignore[no-any-return]


def total_return_series(
    bars: pl.DataFrame, dividends: pl.DataFrame, *, as_of: datetime
) -> pl.DataFrame:
    """Daily total returns from raw closes with dividends reinvested on their ex-dates.

    ``r_t = (close_t + dividend_gbx(ex = t, available_at <= as_of)) / close_{t-1} - 1``.
    A ~100x one-day close ratio (a quotation-unit flip, DEC-020's disease) refuses to
    compute rather than producing a 99% "return"."""
    _require_columns(bars, {"trade_date", "close"}, "benchmark bars")
    frame = bars.sort("trade_date")
    reference = default_reference_data()
    knowable = dividends.filter(pl.col("available_at") <= as_of)
    dividend_by_ex: dict[date, Decimal] = {}
    for row in knowable.iter_rows(named=True):
        amount = reference.convert(Decimal(str(row["amount"])), row["currency"], "GBX")
        dividend_by_ex[row["ex_date"]] = dividend_by_ex.get(row["ex_date"], Decimal(0)) + amount

    dates = frame["trade_date"].to_list()
    closes = [Decimal(str(v)) for v in frame["close"]]
    rows: list[dict[str, object]] = []
    for i in range(1, len(closes)):
        if closes[i - 1] <= 0:
            raise BenchmarkError(f"non-positive close before {dates[i]}")
        ratio = closes[i] / closes[i - 1]
        if ratio > 50 or ratio < Decimal(1) / 50:
            raise BenchmarkError(
                f"~100x close ratio at {dates[i]} — quotation-unit flip, refuse to compute"
            )
        dividend = dividend_by_ex.get(dates[i], Decimal(0))
        rows.append({"date": dates[i], "ret": float((closes[i] + dividend) / closes[i - 1] - 1)})
    return pl.DataFrame(rows, schema={"date": pl.Date, "ret": pl.Float64})


def load_benchmark(name: str, root: Path, *, as_of: datetime) -> BenchmarkSeries:
    spec = BENCHMARKS.get(name)
    if spec is None:
        raise BenchmarkError(f"unknown benchmark {name!r}; known: {sorted(BENCHMARKS)}")
    directory = root / name
    bars = pl.read_parquet(directory / "bars.parquet")
    dividends_path = directory / "dividends.parquet"
    dividends = (
        pl.read_parquet(dividends_path)
        if dividends_path.exists()
        else pl.DataFrame(
            schema={
                "ex_date": pl.Date,
                "amount": pl.Float64,
                "currency": pl.Utf8,
                "available_at": pl.Datetime(time_zone="UTC"),
            }
        )
    )
    return BenchmarkSeries(
        name=name,
        universe=spec["universe"],
        currency=spec["currency"],
        kind=spec["kind"],
        source=spec["source"],
        returns=total_return_series(bars, dividends, as_of=as_of),
    )


# ------------------------------------------------------------------- relative measures


@dataclass(frozen=True)
class RelativeRecord:
    benchmark: str
    benchmark_kind: str
    periods: int
    excess_cagr: float  # geometric: (1+strategy)^(1/y) / (1+benchmark)^(1/y) - 1
    tracking_error: float  # stdev of per-period active returns, annualised
    information_ratio: float | None  # annualised mean active return / tracking error
    benchmark_total_return: float
    strategy_total_return: float
    dropped_dates: tuple[str, ...] = ()

    def to_json(self) -> str:
        payload = {k: getattr(self, k) for k in self.__dataclass_fields__}
        payload["dropped_dates"] = list(self.dropped_dates)
        return json.dumps(payload, indent=2)


def align(
    strategy: pl.DataFrame, benchmark: pl.DataFrame
) -> tuple[pl.DataFrame, pl.DataFrame, list[date]]:
    """Intersect the two (date, ret) frames on dates. The dropped dates are RETURNED,
    never discarded silently — the caller must surface them (the runner records a
    warning). This is the single documented alignment rule."""
    for frame, label in ((strategy, "strategy"), (benchmark, "benchmark")):
        _require_columns(frame, {"date", "ret"}, f"{label} returns")
    common = set(strategy["date"]) & set(benchmark["date"])
    dropped = sorted(set(strategy["date"]).symmetric_difference(benchmark["date"]))
    keep = pl.Series("date", sorted(common))
    return (
        strategy.filter(pl.col("date").is_in(keep)).sort("date"),
        benchmark.filter(pl.col("date").is_in(keep)).sort("date"),
        dropped,
    )


def relative_metrics(
    strategy: pl.DataFrame,
    benchmark: BenchmarkSeries,
    *,
    periods_per_year: int = 252,
) -> RelativeRecord:
    """Excess return, tracking error and information ratio on strictly matched dates.

    Mismatched date sets raise — call :func:`align` first and surface what it dropped."""
    if strategy["date"].to_list() != benchmark.returns["date"].to_list():
        raise MetricsError(
            "strategy and benchmark dates differ — align() first and report the drops"
        )
    a = [float(r) for r in strategy["ret"]]
    b = [float(r) for r in benchmark.returns["ret"]]
    n = len(a)
    if n < 2:
        raise MetricsError("relative metrics need at least two matched periods")
    active = [x - y for x, y in zip(a, b, strict=True)]
    mean_active = sum(active) / n
    variance = sum((x - mean_active) ** 2 for x in active) / (n - 1)
    tracking_error = variance**0.5 * periods_per_year**0.5
    information_ratio = (
        mean_active * periods_per_year / tracking_error if tracking_error > 0 else None
    )
    years = n / periods_per_year
    strategy_total = _compound(a)
    benchmark_total = _compound(b)
    excess_cagr = (1 + strategy_total) ** (1 / years) / (1 + benchmark_total) ** (1 / years) - 1
    return RelativeRecord(
        benchmark=benchmark.name,
        benchmark_kind=benchmark.kind,
        periods=n,
        excess_cagr=excess_cagr,
        tracking_error=tracking_error,
        information_ratio=information_ratio,
        benchmark_total_return=benchmark_total,
        strategy_total_return=strategy_total,
    )


def _compound(returns: list[float]) -> float:
    total = 1.0
    for r in returns:
        total *= 1 + r
    return total - 1


def check_suitability(
    config: BacktestConfig, benchmark: BenchmarkSeries, strategy_dates: list[date]
) -> list[str]:
    """RESEARCH_METHODOLOGY rule 6, mechanically: universe, currency, coverage. The
    realistic failure mode is inattention, so this runs with every benchmarked backtest
    and its findings land in the run's recorded warnings."""
    warnings: list[str] = []
    if benchmark.universe != config.universe:
        warnings.append(
            f"benchmark {benchmark.name} tracks {benchmark.universe}, "
            f"strategy universe is {config.universe}"
        )
    if benchmark.currency != "GBX":
        warnings.append(f"benchmark {benchmark.name} is in {benchmark.currency}, ledger is GBX")
    if strategy_dates and (
        benchmark.start > strategy_dates[0] or benchmark.end < strategy_dates[-1]
    ):
        warnings.append(
            f"benchmark {benchmark.name} covers {benchmark.start}..{benchmark.end}, "
            f"strategy needs {strategy_dates[0]}..{strategy_dates[-1]}"
        )
    return warnings


# ------------------------------------------------------------------------- ingestion


def ingest_benchmarks(*, pace_seconds: float = 0.2) -> None:
    """Fetch benchmark ETF bars and dividends through the standard raw-first pipeline
    and canonicalise into ``data/canonical/benchmarks/<name>/``. Idempotent per run day;
    the raw archive is append-only as everywhere else."""
    import time as time_module

    from trp.canonical.ingest_eodhd import bars_from_eodhd, dividends_from_eodhd
    from trp.config import load_settings
    from trp.domain.identifiers import SecurityId
    from trp.ingestion.raw import RawStore
    from trp.providers.adapters.eodhd import EodhdProvider
    from trp.providers.base import Dataset

    settings = load_settings()
    store = RawStore(settings.raw_dir)
    provider = EodhdProvider()
    ingested_at = datetime.now(UTC)
    for name, spec in BENCHMARKS.items():
        symbol = spec["symbol"]
        directory = settings.canonical_dir / "benchmarks" / name
        directory.mkdir(parents=True, exist_ok=True)
        pages = list(provider.prices(symbol, date(2000, 1, 1), ingested_at.date()))
        for page in pages:
            store.write("eodhd", provider.version, Dataset.PRICES, page)
        action_pages = list(
            provider.corporate_actions(symbol, date(2000, 1, 1), ingested_at.date())
        )
        for page in action_pages:
            store.write("eodhd", provider.version, Dataset.CORPORATE_ACTIONS, page)
        time_module.sleep(pace_seconds)

        pseudo_id = SecurityId(f"BMK-{name}")
        all_bars = []
        for page in pages:
            bars, rejects = bars_from_eodhd(
                page.content, pseudo_id, currency=str(spec["currency"]), ingested_at=ingested_at
            )
            all_bars.extend(bars)
            if rejects:
                raise BenchmarkError(f"{name}: rejected bars: {rejects[:3]}")
        frame = pl.DataFrame([b.model_dump() for b in all_bars]).sort("trade_date")
        frame.write_parquet(directory / "bars.parquet")

        dividend_rows: list[dict[str, object]] = []
        for page in action_pages:
            if "/div/" not in page.endpoint:
                if "/splits/" in page.endpoint and json.loads(page.content):
                    raise BenchmarkError(f"{name}: unexpected split records — adjudicate")
                continue
            dividends, rejects = dividends_from_eodhd(page.content, pseudo_id)
            dividend_rows.extend(d.model_dump() for d in dividends)
            if rejects:
                raise BenchmarkError(f"{name}: rejected dividends: {rejects[:3]}")
        if dividend_rows:
            pl.DataFrame(dividend_rows).sort("ex_date").write_parquet(
                directory / "dividends.parquet"
            )
        (directory / "provenance.json").write_text(
            json.dumps({**spec, "ingested_at": ingested_at.isoformat()}, indent=2)
        )


if __name__ == "__main__":
    from trp.logging import setup_logging

    setup_logging()
    ingest_benchmarks()
    settings_as_of = datetime.combine(datetime.now(UTC).date(), time(23, 59, 59), tzinfo=UTC)
    from trp.config import load_settings as _load

    for benchmark_name in BENCHMARKS:
        series = load_benchmark(
            benchmark_name, _load().canonical_dir / "benchmarks", as_of=settings_as_of
        )
        print(
            f"{benchmark_name}: {series.returns.height} daily returns {series.start}..{series.end}"
        )
