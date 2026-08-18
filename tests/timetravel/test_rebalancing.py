"""QNT-052 timetravel: target weights at a rebalance date are unchanged by any data
dated after it — factor inputs, prices, and the realised-volatility estimate alike."""

from datetime import UTC, date, datetime
from decimal import Decimal

import pytest

from tests.backtest.test_engine import make_config, make_market
from tests.backtest.test_rebalance import REGISTRY, make_context
from tests.factors.test_returns import daily_bars
from trp.backtest.config import Weighting
from trp.backtest.rebalance import factor_strategy
from trp.domain.corporate_actions import Dividend
from trp.domain.identifiers import new_security_id

pytestmark = pytest.mark.timetravel

CLOCK = date(2021, 6, 1)


def _world() -> tuple:
    a, b = sorted([new_security_id(), new_security_id()])
    past = daily_bars(
        a, date(2019, 12, 2), CLOCK, "100", {date(2020, 9, 1): "150", date(2021, 3, 1): "140"}
    ) + daily_bars(b, date(2019, 12, 2), CLOCK, "200", {date(2021, 2, 1): "210"})
    future = daily_bars(a, date(2021, 6, 2), date(2021, 12, 31), "5") + daily_bars(
        b, date(2021, 6, 2), date(2021, 12, 31), "900"
    )
    late_actions = [
        Dividend(
            security_id=a,
            ex_date=date(2021, 4, 1),
            source="t",
            available_at=datetime(2021, 9, 1, tzinfo=UTC),  # announced after the clock
            amount=Decimal("50"),
            currency="GBX",
        )
    ]
    return a, b, past, future, late_actions


@pytest.mark.parametrize(
    "weighting", [Weighting.EQUAL, Weighting.FACTOR_SCORE, Weighting.INVERSE_VOLATILITY]
)
def test_targets_are_invariant_to_future_data(weighting: Weighting) -> None:
    a, b, past, future, late_actions = _world()
    config = make_config(top_n=2, weighting=weighting)
    strategy = factor_strategy(REGISTRY.get("momentum_12_1"), config)
    members = frozenset({a, b})
    clean = strategy(make_context(make_market(past, []), members, CLOCK), {}, Decimal("1000000"))
    polluted = strategy(
        make_context(make_market(past + future, late_actions), members, CLOCK),
        {},
        Decimal("1000000"),
    )
    assert clean == polluted
    assert clean  # the fixture actually selects something


def test_realised_volatility_uses_only_data_at_the_clock() -> None:
    a, b, past, future, late_actions = _world()
    members = frozenset({a, b})
    clean = make_context(make_market(past, []), members, CLOCK)
    polluted = make_context(make_market(past + future, late_actions), members, CLOCK)
    for sid in (a, b):
        vol_clean = clean.realised_volatility(sid)
        vol_polluted = polluted.realised_volatility(sid)
        assert vol_clean is not None and vol_clean > 0
        assert vol_clean == vol_polluted


def test_actions_dated_after_the_clock_do_not_exclude_the_security() -> None:
    """Regression: the anchor-gap guard once tested actions beyond the sliced window and
    excluded nearly every dividend payer from the cross-section."""
    a, b, past, future, _late_actions = _world()
    far_future_dividend = Dividend(
        security_id=a,
        ex_date=date(2026, 1, 15),  # years past the clock
        source="t",
        available_at=datetime(2026, 1, 15, tzinfo=UTC),
        amount=Decimal("10"),
        currency="GBX",
    )
    members = frozenset({a, b})
    context = make_context(make_market(past + future, [far_future_dividend]), members, CLOCK)
    frame = context.factor_values(REGISTRY.get("momentum_12_1"), members)
    ok_rows = frame.filter(frame["status"] == "ok")
    assert ok_rows.height == 2  # both securities score; the future action is inert
