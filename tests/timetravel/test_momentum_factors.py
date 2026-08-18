"""Momentum values at date t are immune to everything after t (QNT-044)."""

from datetime import UTC, date, datetime
from decimal import Decimal

import pytest

from tests.factors.test_returns import daily_bars
from trp.domain.corporate_actions import Dividend
from trp.domain.identifiers import new_security_id
from trp.factors.compute import ComputeContext, compute_factor
from trp.factors.registry import FactorRegistry

pytestmark = pytest.mark.timetravel

REGISTRY = FactorRegistry.load()
T = date(2021, 6, 30)
AS_OF = datetime(2021, 7, 1, tzinfo=UTC)


def momentum_at(sid: object, bars: list, actions: list, as_of: datetime) -> float | None:  # type: ignore[type-arg]
    context = ComputeContext(
        security_ids=[sid],  # type: ignore[list-item]
        end=T,
        as_of=as_of,
        bars=bars,
        actions=actions,
    )
    return compute_factor(REGISTRY.get("momentum_12_1"), context).to_dicts()[0]["value"]


def test_prices_after_t_do_not_change_the_factor_at_t() -> None:
    sid = new_security_id()
    up_to_t = daily_bars(sid, date(2020, 6, 1), T, "1000", {date(2021, 3, 1): "1100"})
    with_future = up_to_t + daily_bars(
        sid, date(2021, 7, 1), date(2021, 12, 31), "5000"
    )  # a wild rally AFTER t
    assert momentum_at(sid, up_to_t, [], AS_OF) == momentum_at(sid, with_future, [], AS_OF)


def test_actions_announced_after_t_do_not_change_the_factor_at_t() -> None:
    sid = new_security_id()
    bars = daily_bars(sid, date(2020, 6, 1), T, "1000")
    late = Dividend(
        security_id=sid,
        ex_date=date(2021, 2, 1),
        source="t",
        available_at=datetime(2021, 9, 1, tzinfo=UTC),  # announced after as_of
        amount=Decimal("50"),
        currency="GBX",
    )
    assert momentum_at(sid, bars, [late], AS_OF) == pytest.approx(0.0)
    assert momentum_at(sid, bars, [late], datetime(2021, 10, 1, tzinfo=UTC)) == pytest.approx(
        1 / 0.95 - 1
    )
