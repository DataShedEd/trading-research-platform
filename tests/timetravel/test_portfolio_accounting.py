"""QNT-051 timetravel: the ledger only ever reacts to actions the run could know about.

Late knowledge is applied on the knowledge date, never retroactively: a dividend the
vendor published in September for a February ex-date credits in September, and every
valuation before September is identical to a run that never saw the record.
"""

from datetime import UTC, date, datetime
from decimal import Decimal

import pytest

from tests.backtest.test_engine import make_config, make_market, run_engine
from tests.factors.test_returns import daily_bars
from trp.domain.corporate_actions import DelistingAction, Dividend
from trp.domain.identifiers import new_security_id
from trp.domain.security import DelistingReason

pytestmark = pytest.mark.timetravel

END = date(2021, 6, 30)


def hold(sid):  # type: ignore[no-untyped-def]
    """A strategy that holds 100 shares of `sid` throughout."""

    def strategy(context, positions, value):  # type: ignore[no-untyped-def]
        return {sid: 100}

    return strategy


def test_action_announced_after_the_window_never_touches_the_ledger() -> None:
    sid = new_security_id()
    bars = daily_bars(sid, date(2020, 11, 2), END, "100")
    unknowable = Dividend(
        security_id=sid,
        ex_date=date(2021, 3, 1),
        source="t",
        available_at=datetime(2021, 8, 1, tzinfo=UTC),  # after the run ends
        amount=Decimal("7"),
        currency="GBX",
    )
    with_action = run_engine(make_config(), make_market(bars, [unknowable]), hold(sid))
    without = run_engine(make_config(), make_market(bars, []), hold(sid))
    assert with_action.daily.equals(without.daily)
    assert with_action.events.equals(without.events)


def test_late_knowledge_applies_on_the_knowledge_date_not_the_ex_date() -> None:
    sid = new_security_id()
    bars = daily_bars(sid, date(2020, 11, 2), END, "100")
    late = Dividend(
        security_id=sid,
        ex_date=date(2021, 2, 1),
        source="t",
        available_at=datetime(2021, 5, 4, 12, 0, tzinfo=UTC),  # known three months later
        amount=Decimal("7"),
        currency="GBX",
    )
    result = run_engine(make_config(), make_market(bars, [late]), hold(sid))
    dividends = result.events.filter(result.events["kind"] == "dividend")
    assert dividends["on"].to_list() == ["2021-05-04"]  # events store JSON-serialised values
    daily = dict(zip(result.daily["date"], result.daily["value"], strict=True))
    assert daily[date(2021, 2, 1)] == 1000000.0  # nothing credited on the true ex-date
    assert daily[date(2021, 5, 4)] == 1000700.0  # credited when knowable (100 shares * 7p)


def test_delisting_learned_later_does_not_rewrite_earlier_valuations() -> None:
    sid = new_security_id()
    bars = daily_bars(sid, date(2020, 11, 2), date(2021, 5, 20), "100")
    late_delisting = DelistingAction(
        security_id=sid,
        ex_date=date(2021, 5, 21),
        source="t",
        available_at=datetime(2021, 6, 1, tzinfo=UTC),  # we learn ten days later
        reason=DelistingReason.FAILURE,
        last_trading_date=date(2021, 5, 20),
    )
    with_action = run_engine(make_config(), make_market(bars, [late_delisting]), hold(sid))
    without = run_engine(make_config(), make_market(bars, []), hold(sid))
    knowledge_day = date(2021, 6, 1)
    for day, with_value, without_value in zip(
        with_action.daily["date"], with_action.daily["value"], without.daily["value"], strict=True
    ):
        if day < knowledge_day:
            assert with_value == without_value  # history identical before knowledge
        else:
            # The write-off lands exactly at knowledge. (In the record-free run the
            # DEC-019 forced exit eventually fires instead — value-neutral by design,
            # so the 10000 gap persists.)
            assert with_value == without_value - 10000.0
