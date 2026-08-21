"""QNT-048 timetravel: a composite score at t is a function of knowledge at t, changing
only through its components as information genuinely arrives."""

# ruff: noqa: F811 - pytest fixtures are imported by name and reused as parameters

from datetime import UTC, date, datetime

import pytest

from tests.factors.test_quality import SNAPSHOT, records
from tests.factors.test_returns import daily_bars
from tests.factors.test_value import fx_root, store  # noqa: F401 - pytest fixtures
from trp.canonical.fundamentals.storage import write_fundamentals
from trp.domain.identifiers import new_security_id
from trp.factors.compute import ComputeContext, compute_factor
from trp.factors.registry import FactorRegistry

pytestmark = pytest.mark.timetravel

REGISTRY = FactorRegistry.load()
CLOCK = date(2021, 6, 30)


def seed_pair(store):  # type: ignore[no-untyped-def]
    """Two securities with full snapshots and enough price history for momentum_12_1."""
    a, b = sorted([new_security_id(), new_security_id()])
    for sid, net_income in ((a, "100"), (b, "300")):
        write_fundamentals(
            records(
                sid,
                {**SNAPSHOT, "net_income": net_income, "shares_outstanding": "1000"},
                date(2020, 12, 31),
                datetime(2021, 4, 30, tzinfo=UTC),
            ),
            store,
            source="fixture",
        )
    bars = daily_bars(a, date(2019, 12, 2), CLOCK, "400", {date(2020, 9, 1): "500"}) + daily_bars(
        b, date(2019, 12, 2), CLOCK, "400"
    )
    return a, b, bars


def context_of(store, fx_root, bars, *ids):  # type: ignore[no-untyped-def]
    return ComputeContext(
        security_ids=sorted(ids),
        end=CLOCK,
        as_of=datetime(2021, 7, 1, tzinfo=UTC),
        bars=bars,
        fundamentals_root=store,
        fx_root=fx_root,
    )


def test_composite_is_invariant_to_future_data(store, fx_root) -> None:  # type: ignore[no-untyped-def]
    a, b, bars = seed_pair(store)
    clean = compute_factor(
        REGISTRY.get("qvm_equal"), context_of(store, fx_root, bars, a, b)
    ).to_dicts()
    future_bars = daily_bars(a, date(2021, 7, 1), date(2021, 12, 31), "9")
    write_fundamentals(  # a blowout year, knowable only in 2022
        records(
            a,
            {**SNAPSHOT, "net_income": "9999", "shares_outstanding": "1000"},
            date(2021, 12, 31),
            datetime(2022, 4, 30, tzinfo=UTC),
        ),
        store,
        source="fixture",
    )
    polluted = compute_factor(
        REGISTRY.get("qvm_equal"), context_of(store, fx_root, bars + future_bars, a, b)
    ).to_dicts()
    assert [r["value"] for r in clean] == pytest.approx([r["value"] for r in polluted])
    assert [r["status"] for r in clean] == [r["status"] for r in polluted]


def test_composite_changes_when_information_genuinely_arrives(store, fx_root) -> None:  # type: ignore[no-untyped-def]
    a, b, bars = seed_pair(store)
    before = compute_factor(
        REGISTRY.get("qvm_equal"), context_of(store, fx_root, bars, a, b)
    ).to_dicts()
    write_fundamentals(  # a restatement of a's earnings, knowable 15 May 2021 (< clock)
        records(
            a,
            {"net_income": "500"},
            date(2020, 12, 31),
            datetime(2021, 5, 15, tzinfo=UTC),
            revision=1,
        ),
        store,
        source="fixture",
    )
    after = compute_factor(
        REGISTRY.get("qvm_equal"), context_of(store, fx_root, bars, a, b)
    ).to_dicts()
    assert [r["value"] for r in before] != [r["value"] for r in after]
