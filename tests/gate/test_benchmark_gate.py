"""QNT-055 gate: the ISF total-return construction validated against the accumulating
share class (CUKX) on real data. Run with `uv run pytest -m gate`."""

import math
from datetime import UTC, date, datetime, time

import polars as pl
import pytest

from trp.backtest.benchmark import align, load_benchmark
from trp.config import load_settings

SETTINGS = load_settings()
BENCHMARKS_DIR = SETTINGS.canonical_dir / "benchmarks"

pytestmark = [
    pytest.mark.gate,
    pytest.mark.skipif(
        not (BENCHMARKS_DIR / "isf-xlon-tr" / "bars.parquet").exists(),
        reason="benchmark datasets not ingested",
    ),
]

AS_OF = datetime.combine(date(2026, 12, 31), time(23, 59, 59), tzinfo=UTC)
# CUKX's early years are thin (about 30% of sessions missing before 2016); the
# cross-check runs where both series are complete.
OVERLAP_START = date(2016, 1, 1)


@pytest.fixture(scope="module")
def isf():  # type: ignore[no-untyped-def]
    return load_benchmark("isf-xlon-tr", BENCHMARKS_DIR, as_of=AS_OF)


@pytest.fixture(scope="module")
def cukx():  # type: ignore[no-untyped-def]
    return load_benchmark("cukx-xlon-acc", BENCHMARKS_DIR, as_of=AS_OF)


def test_total_return_beats_price_only_by_roughly_the_dividend_yield(isf) -> None:  # type: ignore[no-untyped-def]
    bars = pl.read_parquet(BENCHMARKS_DIR / "isf-xlon-tr" / "bars.parquet").sort("trade_date")
    recent = bars.filter(pl.col("trade_date") >= OVERLAP_START)
    price_total = float(recent["close"][-1]) / float(recent["close"][0]) - 1
    tr = isf.returns.filter(pl.col("date") >= OVERLAP_START)
    tr_total = math.prod(1 + r for r in tr["ret"]) - 1
    years = tr.height / 252
    implied_yield = (1 + tr_total) ** (1 / years) - (1 + price_total) ** (1 / years)
    assert 0.025 < implied_yield < 0.055  # FTSE 100 yield territory, reinvested


def test_reinvested_distributing_class_tracks_the_accumulating_class(isf, cukx) -> None:  # type: ignore[no-untyped-def]
    a, b, dropped = align(
        isf.returns.filter(pl.col("date") >= OVERLAP_START),
        cukx.returns.filter(pl.col("date") >= OVERLAP_START),
    )
    assert not dropped  # both share classes trade every XLON session from 2016
    total_a = math.prod(1 + r for r in a["ret"])
    total_b = math.prod(1 + r for r in b["ret"])
    years = a.height / 252
    annual_gap = (total_a / total_b) ** (1 / years) - 1
    assert abs(annual_gap) < 0.003  # within 30bp/yr: the construction is sound


def test_risk_free_series_matches_known_rate_regimes() -> None:
    from trp.backtest.riskfree import load_risk_free, window_mean_rate

    series = load_risk_free(SETTINGS.canonical_dir / "riskfree")
    zirp, _ = window_mean_rate(series, date(2015, 1, 1), date(2015, 12, 31))
    assert 0.0 < zirp < 0.01  # UK short rates were near zero in 2015
    tightening, _ = window_mean_rate(series, date(2023, 1, 1), date(2023, 12, 31))
    assert 0.035 < tightening < 0.06  # and 4-5% through 2023
