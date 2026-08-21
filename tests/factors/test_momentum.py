"""Momentum factor set (QNT-044): the shipped definitions against hand-derived fixtures.

Tolerance: pytest.approx defaults (rel 1e-6) — the arithmetic is deterministic float on
exact adjustment factors, so expectations hold tightly.
"""

from datetime import UTC, date, datetime
from decimal import Decimal

import pytest

from tests.factors.test_returns import daily_bars
from trp.domain.corporate_actions import Dividend, Split
from trp.domain.identifiers import SecurityId, new_security_id
from trp.factors.compute import ComputeContext, compute_factor
from trp.factors.registry import FactorRegistry

AS_OF = datetime(2022, 6, 1, tzinfo=UTC)
END = date(2021, 12, 31)
REGISTRY = FactorRegistry.load()


def value_of(
    name: str,
    sid: SecurityId,
    bars: list,  # type: ignore[type-arg]
    actions: list | None = None,  # type: ignore[type-arg]
    end: date = END,
    as_of: datetime = AS_OF,
) -> dict[str, object]:
    context = ComputeContext(
        security_ids=[sid], end=end, as_of=as_of, bars=bars, actions=actions or []
    )
    return compute_factor(REGISTRY.get(name), context).to_dicts()[0]


def test_all_four_definitions_load_from_config() -> None:
    names = {d.name for d in REGISTRY.definitions()}
    assert {
        "momentum_12_1",
        "momentum_6_1",
        "momentum_3_0",
        "momentum_12_1_vol_adjusted",
    } <= names
    for definition in REGISTRY.definitions():
        if definition.transform.startswith("window_"):
            assert "months" in definition.parameters  # windows in config, never in Python


def test_12_1_momentum_across_a_split() -> None:
    sid = new_security_id()
    ex = date(2021, 6, 1)
    # 1000p, 2:1 split (500p), drifts to 550p by November. Hand-derived: adjusted
    # 500 -> 550 = +10%; the split itself contributes nothing.
    bars = daily_bars(sid, date(2020, 11, 2), END, "1000", {ex: "500", date(2021, 11, 1): "550"})
    split = Split(
        security_id=sid, ex_date=ex, source="t", available_at=AS_OF, new_shares=2, old_shares=1
    )
    row = value_of("momentum_12_1", sid, bars, [split])
    assert row["status"] == "ok"
    assert row["value"] == pytest.approx(0.10)


def test_6_1_momentum_across_a_dividend() -> None:
    sid = new_security_id()
    # Flat 1000p; 50p (stated GBP 0.50) dividend in September. 6-1 window ending
    # 30 Nov: reinvested return = 1/0.95 - 1.
    bars = daily_bars(sid, date(2021, 1, 4), END, "1000")
    dividend = Dividend(
        security_id=sid,
        ex_date=date(2021, 9, 1),
        source="t",
        available_at=AS_OF,
        amount=Decimal("0.50"),
        currency="GBP",
    )
    row = value_of("momentum_6_1", sid, bars, [dividend])
    assert row["value"] == pytest.approx(1 / 0.95 - 1)


def test_skip_period_separates_3_0_from_12_1() -> None:
    sid = new_security_id()
    # A +20% move on 10 December — inside 12-1's skipped month, inside 3-0's window.
    bars = daily_bars(sid, date(2020, 11, 2), END, "1000", {date(2021, 12, 10): "1200"})
    with_skip = value_of("momentum_12_1", sid, bars)
    without = value_of("momentum_3_0", sid, bars)
    assert with_skip["value"] == pytest.approx(0.0)
    assert without["value"] == pytest.approx(0.20)


def test_insufficient_history_is_typed_not_shortened() -> None:
    sid = new_security_id()
    bars = daily_bars(sid, date(2021, 9, 1), END, "1000")  # four months of history
    row = value_of("momentum_12_1", sid, bars)
    assert row["status"] == "insufficient_data"
    assert row["value"] is None
    assert value_of("momentum_3_0", sid, bars)["status"] == "ok"


def test_vol_adjusted_momentum_and_near_zero_volatility() -> None:
    sid = new_security_id()
    # Alternate 1000/1010 daily: real volatility, near-zero net drift.
    sessions = daily_bars(sid, date(2020, 11, 2), END, "1000")
    wobble = [
        bar if i % 2 == 0 else bar.model_copy()  # placeholder replaced below
        for i, bar in enumerate(sessions)
    ]
    from trp.domain.security import revalidated_copy

    wobble = [
        bar
        if i % 2 == 0
        else revalidated_copy(
            bar,
            open=Decimal("1010"),
            high=Decimal("1010"),
            low=Decimal("1010"),
            close=Decimal("1010"),
        )
        for i, bar in enumerate(sessions)
    ]
    lively = value_of("momentum_12_1_vol_adjusted", sid, wobble)
    assert lively["status"] == "ok"
    plain = value_of("momentum_12_1", sid, wobble)
    # Same window, same series: the ratio's numerator is the plain momentum value.
    assert plain["status"] == "ok"

    flat = daily_bars(sid, date(2020, 11, 2), END, "1000")
    becalmed = value_of("momentum_12_1_vol_adjusted", sid, flat)
    assert becalmed["status"] == "insufficient_data"  # near-zero vol: typed, no blow-up
    assert "near-zero volatility" in str(becalmed["warnings"])
