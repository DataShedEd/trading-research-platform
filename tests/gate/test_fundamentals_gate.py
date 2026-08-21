"""QNT-097 gate: canonical fundamentals coverage and spot checks on the real store.
Run with `uv run pytest -m gate`."""

from datetime import UTC, datetime

import polars as pl
import pytest

from trp.canonical.fundamentals.queries import fundamentals
from trp.config import load_settings

SETTINGS = load_settings()
ROOT = SETTINGS.canonical_dir / "fundamentals"

pytestmark = [
    pytest.mark.gate,
    pytest.mark.timetravel,
    pytest.mark.skipif(
        not any(ROOT.glob("period_year=*/part-*.parquet")),
        reason="canonical fundamentals not ingested",
    ),
]


def security_id_of(name_fragment: str) -> str:
    frame = pl.read_parquet(SETTINGS.canonical_dir / "securities" / "securities.parquet")
    return str(frame.filter(pl.col("name").str.contains(name_fragment))["security_id"][0])


def test_coverage_spans_the_ftse_ever_universe() -> None:
    files = ROOT.glob("period_year=*/part-*.parquet")
    frame = pl.concat([pl.read_parquet(f, columns=["security_id"]) for f in files])
    securities = frame["security_id"].n_unique()
    assert securities > 170  # 191 payloads, less names with no mappable statements


def annual_2020_revenue(as_of: datetime) -> pl.DataFrame:
    tesco = security_id_of("Tesco")
    frame = fundamentals(ROOT, [tesco], ["revenue"], as_of=as_of)
    return frame.filter(
        (pl.col("period_end").dt.year() == 2020) & (pl.col("period_type") == "annual")
    )


def test_tesco_annual_revenue_is_knowable_only_after_the_dec007_lag() -> None:
    # Tesco's FY ends late February; at 1 March the year-end is NOT yet knowable...
    assert annual_2020_revenue(datetime(2020, 3, 1, tzinfo=UTC)).height == 0
    # ...but after the 120-day lag it is, at the right magnitude (GBP 58.1bn FY19/20).
    later = annual_2020_revenue(datetime(2020, 8, 1, tzinfo=UTC))
    assert later.height >= 1
    assert 4e10 < float(later["value"][0]) < 8e10
    assert later["currency"][0] == "GBP"
    assert bool(later["availability_imputed"][0]) is True


def test_deep_history_reaches_the_nineteen_eighties() -> None:
    tesco = security_id_of("Tesco")
    frame = fundamentals(ROOT, [tesco], ["revenue"], as_of=datetime(2026, 8, 1, tzinfo=UTC))
    annual = frame.filter(pl.col("period_type") == "annual").sort("period_end")
    assert annual.height >= 40  # 1986 onwards
    assert 3e9 < float(annual["value"][0]) < 4e9  # Tesco FY1986: ~GBP 3.36bn


def test_shell_reports_in_usd_unconverted() -> None:
    shell = security_id_of("Shell plc")
    frame = fundamentals(ROOT, [shell], ["net_income"], as_of=datetime(2024, 12, 31, tzinfo=UTC))
    annual = frame.filter(pl.col("period_end") == pl.date(2023, 12, 31))
    assert annual.height >= 1
    assert annual["currency"][0] == "USD"  # stored as filed; QNT-023 converts at query time
    assert 1.5e10 < float(annual["value"][0]) < 2.5e10  # Shell FY2023 ~USD 19.4bn


def test_dividends_paid_carry_the_outflow_negative_convention() -> None:
    tesco = security_id_of("Tesco")
    frame = fundamentals(ROOT, [tesco], ["dividends_paid"], as_of=datetime(2026, 8, 1, tzinfo=UTC))
    values = [float(v) for v in frame["value"]]
    assert values, "no dividends_paid rows for Tesco"
    negative_share = sum(1 for v in values if v < 0) / len(values)
    assert negative_share > 0.95  # the QNT-097 sign flip, in the store
