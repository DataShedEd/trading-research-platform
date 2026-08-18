"""QNT-055 timetravel: a benchmark's value at date t uses only data knowable at t."""

from datetime import UTC, date, datetime

import pytest

from tests.backtest.test_benchmark import AS_OF, bar_frame, dividend_frame
from trp.backtest.benchmark import total_return_series

pytestmark = pytest.mark.timetravel

PAST = [(date(2021, 3, d), "1000") for d in (1, 2, 3, 4, 5)]


def test_later_bars_do_not_change_earlier_returns() -> None:
    clean = total_return_series(bar_frame(PAST), dividend_frame([]).clear(), as_of=AS_OF)
    extended = total_return_series(
        bar_frame([*PAST, (date(2021, 3, 8), "5000")]),  # wild print later
        dividend_frame([]).clear(),
        as_of=AS_OF,
    )
    assert extended.head(clean.height).equals(clean)


def test_dividends_not_yet_knowable_are_excluded() -> None:
    late = dividend_frame(
        [(date(2021, 3, 3), "0.50", "GBP", datetime(2022, 6, 1, tzinfo=UTC))]
    )  # backfilled by the vendor long after as_of
    with_late = total_return_series(bar_frame(PAST), late, as_of=AS_OF)
    without = total_return_series(bar_frame(PAST), late.clear(), as_of=AS_OF)
    assert with_late.equals(without)
    # ...and once knowledge advances past the backfill, the dividend appears.
    later_view = total_return_series(bar_frame(PAST), late, as_of=datetime(2022, 7, 1, tzinfo=UTC))
    assert later_view["ret"].to_list()[1] == pytest.approx(0.05)
