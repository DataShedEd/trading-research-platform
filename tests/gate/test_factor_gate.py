"""QNT-045/046 gate: fundamental factors over the real FTSE 100 cross-section.
Run with `uv run pytest -m gate`."""

from datetime import UTC, date, datetime, time

import pytest

from trp.canonical.price_store import read_bars
from trp.canonical.unit_repair import REPAIRED_SOURCE
from trp.config import load_settings
from trp.factors.compute import ComputeContext, compute_factor
from trp.factors.registry import FactorRegistry
from trp.universe.query import UniverseQuery

SETTINGS = load_settings()

pytestmark = [
    pytest.mark.gate,
    pytest.mark.timetravel,
    pytest.mark.skipif(
        not any((SETTINGS.canonical_dir / "fundamentals").glob("period_year=*/part-*.parquet")),
        reason="canonical fundamentals not ingested",
    ),
]

CLOCK = date(2020, 6, 30)

# (factor, minimum computable of 100, plausible median band)
EXPECTATIONS = [
    ("roe", 90, (0.05, 0.30)),
    ("gross_profitability", 90, (0.05, 0.50)),
    ("roic", 90, (0.04, 0.25)),
    ("earnings_yield", 90, (0.02, 0.12)),
    ("book_to_market", 90, (0.15, 1.00)),
    ("ebitda_ev_yield", 85, (0.04, 0.20)),
    ("shareholder_yield", 85, (0.02, 0.10)),
]


@pytest.fixture(scope="module")
def context() -> ComputeContext:
    as_of = datetime.combine(CLOCK, time(23, 59, 59), tzinfo=UTC)
    members = UniverseQuery(SETTINGS.canonical_dir / "universes").members(
        "FTSE100", CLOCK, as_of=as_of
    )
    bars = read_bars(
        SETTINGS.canonical_dir / "prices",
        start=date(2020, 5, 1),
        end=CLOCK,
        sources=[REPAIRED_SOURCE],
        security_ids=[str(x) for x in members],
    )
    return ComputeContext(
        security_ids=sorted(members),
        end=CLOCK,
        as_of=as_of,
        bars=bars,
        fundamentals_root=SETTINGS.canonical_dir / "fundamentals",
        fx_root=SETTINGS.canonical_dir / "fx",
        shares_root=SETTINGS.canonical_dir / "shares",
    )


@pytest.mark.parametrize("name, minimum_ok, band", EXPECTATIONS)
def test_cross_section_coverage_and_plausibility(
    context: ComputeContext, name: str, minimum_ok: int, band: tuple[float, float]
) -> None:
    frame = compute_factor(FactorRegistry.load().get(name), context)
    ok = frame.filter(frame["status"] == "ok")
    assert ok.height >= minimum_ok, f"{name}: only {ok.height}/100 computable"
    values = sorted(ok["value"].to_list())
    median = values[len(values) // 2]
    low, high = band
    assert low < median < high, f"{name}: median {median:.4f} outside [{low}, {high}]"


def test_market_cap_harness_has_no_unadjudicated_flags() -> None:
    """QNT-098: every implausible FTSE-member market-cap month is on the documented
    exclusion list — the list may only shrink."""
    import polars as pl

    from trp.canonical.price_overrides import MARKET_VALUE_EXCLUSIONS
    from trp.canonical.shares import validate_market_caps

    flagged = validate_market_caps()
    residual = flagged.filter(~pl.col("security_id").is_in(list(MARKET_VALUE_EXCLUSIONS)))
    assert residual.height == 0, residual.head(10)
