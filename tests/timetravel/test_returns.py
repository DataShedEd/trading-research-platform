"""Returns are point-in-time: what was published after ``as_of`` cannot change them."""

from datetime import UTC, date, datetime
from decimal import Decimal

import pytest

from tests.factors.test_returns import daily_bars
from trp.domain.corporate_actions import DelistingAction, Dividend
from trp.domain.identifiers import new_security_id
from trp.domain.security import DelistingReason
from trp.factors.returns import ReturnsEngine, ReturnStatus, WindowSpec

pytestmark = pytest.mark.timetravel

PUBLISHED_LATE = datetime(2021, 9, 1, tzinfo=UTC)
BEFORE = datetime(2021, 8, 1, tzinfo=UTC)
AFTER = datetime(2021, 10, 1, tzinfo=UTC)


def test_late_published_dividend_cannot_change_an_earlier_return() -> None:
    sid = new_security_id()
    bars = daily_bars(sid, date(2020, 6, 1), date(2021, 7, 30), "1000")
    late_dividend = Dividend(
        security_id=sid,
        ex_date=date(2021, 3, 1),
        source="t",
        available_at=PUBLISHED_LATE,  # vendor adds it months later
        amount=Decimal("50"),
        currency="GBX",
    )
    window = WindowSpec(months=12)
    end = date(2021, 7, 30)

    early = ReturnsEngine(bars, [late_dividend], as_of=BEFORE)
    late = ReturnsEngine(bars, [late_dividend], as_of=AFTER)
    assert early.window_return(sid, end, window).value == pytest.approx(0.0)
    assert late.window_return(sid, end, window).value == pytest.approx(1 / 0.95 - 1)


def test_delisting_recorded_later_does_not_rewrite_an_earlier_computation() -> None:
    sid = new_security_id()
    bars = daily_bars(sid, date(2020, 12, 1), date(2021, 6, 30), "100")
    failure = DelistingAction(
        security_id=sid,
        ex_date=date(2021, 7, 1),
        source="t",
        available_at=PUBLISHED_LATE,  # we learn of it in September
        reason=DelistingReason.FAILURE,
    )
    window = WindowSpec(months=12)
    end = date(2021, 12, 31)

    # Before we knew: honestly insufficient — the bars just stop.
    early = ReturnsEngine(bars, [failure], as_of=BEFORE).window_return(sid, end, window)
    assert early.status is ReturnStatus.INSUFFICIENT_DATA
    # After: the failure is knowable and the return is a total loss.
    late = ReturnsEngine(bars, [failure], as_of=AFTER).window_return(sid, end, window)
    assert late.status is ReturnStatus.OK
    assert late.value == pytest.approx(-1.0)
