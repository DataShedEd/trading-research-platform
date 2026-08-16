"""Trading calendar behaviour, asserted against hand-checked LSE and NYSE dates.

Every expected value here was worked out from the published exchange holiday schedule, not
from the library's own output, so a future dependency update that changes historical
holiday data fails these tests instead of silently changing backtest results.
"""

from datetime import date

import pytest

from trp.canonical.calendars import (
    CalendarRangeExhausted,
    DateOutOfCalendarRange,
    TradingCalendar,
    UnknownExchange,
    get_trading_calendar,
)


@pytest.fixture(scope="module")
def lse() -> TradingCalendar:
    return get_trading_calendar("XLON")


class TestRegistry:
    def test_known_mics_resolve(self) -> None:
        for mic in ("XLON", "XNYS", "XNAS"):
            assert get_trading_calendar(mic).mic == mic

    def test_calendars_are_cached_per_exchange(self) -> None:
        assert get_trading_calendar("XLON") is get_trading_calendar("XLON")

    def test_unknown_mic_raises(self) -> None:
        with pytest.raises(UnknownExchange):
            get_trading_calendar("XPAR")

    def test_unknown_mic_raises_on_direct_construction(self) -> None:
        with pytest.raises(UnknownExchange):
            TradingCalendar("XPAR")


class TestIsTradingDay:
    def test_christmas_closure_and_the_days_around_it(self, lse: TradingCalendar) -> None:
        # 2012: Christmas Eve was a (half) session, the 25th and 26th were bank holidays,
        # and the 27th a full session.
        assert lse.is_trading_day(date(2012, 12, 24))
        assert not lse.is_trading_day(date(2012, 12, 25))
        assert not lse.is_trading_day(date(2012, 12, 26))
        assert lse.is_trading_day(date(2012, 12, 27))

    def test_diamond_jubilee_bank_holiday(self, lse: TradingCalendar) -> None:
        # The extra 2012 Diamond Jubilee holiday (Tue 5 June) with the spring bank holiday
        # moved to Mon 4 June: a four-day closure that pure weekday logic gets wrong.
        assert lse.is_trading_day(date(2012, 6, 1))
        assert not lse.is_trading_day(date(2012, 6, 4))
        assert not lse.is_trading_day(date(2012, 6, 5))
        assert lse.is_trading_day(date(2012, 6, 6))

    def test_good_friday_and_easter_monday(self, lse: TradingCalendar) -> None:
        assert not lse.is_trading_day(date(2023, 4, 7))
        assert not lse.is_trading_day(date(2023, 4, 10))
        assert lse.is_trading_day(date(2023, 4, 11))

    def test_ordinary_weekend(self, lse: TradingCalendar) -> None:
        assert lse.is_trading_day(date(2023, 6, 16))
        assert not lse.is_trading_day(date(2023, 6, 17))
        assert not lse.is_trading_day(date(2023, 6, 18))
        assert lse.is_trading_day(date(2023, 6, 19))

    def test_us_calendars_differ_from_lse(self) -> None:
        # Thanksgiving 2023 closes New York and not London; the late-May UK bank holiday
        # closes London and not New York (US Memorial Day fell a week later in 2023).
        nyse = get_trading_calendar("XNYS")
        lse = get_trading_calendar("XLON")
        assert not nyse.is_trading_day(date(2023, 11, 23))
        assert lse.is_trading_day(date(2023, 11, 23))
        assert not lse.is_trading_day(date(2023, 5, 29))


class TestHalfDays:
    def test_christmas_eve_is_a_half_day_and_a_trading_day(self, lse: TradingCalendar) -> None:
        assert lse.is_half_day(date(2012, 12, 24))
        assert lse.is_trading_day(date(2012, 12, 24))

    def test_new_years_eve_is_a_half_day(self, lse: TradingCalendar) -> None:
        assert lse.is_half_day(date(2012, 12, 31))

    def test_full_session_is_not_a_half_day(self, lse: TradingCalendar) -> None:
        assert not lse.is_half_day(date(2012, 12, 27))

    def test_holiday_is_not_a_half_day(self, lse: TradingCalendar) -> None:
        assert not lse.is_half_day(date(2012, 12, 25))

    def test_nyse_early_close(self) -> None:
        # The NYSE closes at 13:00 on the day after Thanksgiving.
        nyse = get_trading_calendar("XNYS")
        assert nyse.is_half_day(date(2023, 11, 24))
        assert nyse.is_trading_day(date(2023, 11, 24))


class TestNextAndPreviousTradingDay:
    def test_across_an_ordinary_weekend(self, lse: TradingCalendar) -> None:
        assert lse.next_trading_day(date(2023, 6, 16)) == date(2023, 6, 19)
        assert lse.previous_trading_day(date(2023, 6, 19)) == date(2023, 6, 16)

    def test_from_a_non_trading_day(self, lse: TradingCalendar) -> None:
        assert lse.next_trading_day(date(2023, 6, 17)) == date(2023, 6, 19)
        assert lse.previous_trading_day(date(2023, 6, 18)) == date(2023, 6, 16)

    def test_across_the_four_day_diamond_jubilee_closure(self, lse: TradingCalendar) -> None:
        # Friday 1 June 2012 → Wednesday 6 June 2012, skipping the weekend and both
        # bank holidays. This is the "immediately after a multi-day closure" case.
        assert lse.next_trading_day(date(2012, 6, 1)) == date(2012, 6, 6)
        assert lse.previous_trading_day(date(2012, 6, 6)) == date(2012, 6, 1)

    def test_across_the_christmas_closure(self, lse: TradingCalendar) -> None:
        assert lse.next_trading_day(date(2012, 12, 24)) == date(2012, 12, 27)
        assert lse.previous_trading_day(date(2012, 12, 27)) == date(2012, 12, 24)

    def test_strictly_after_and_strictly_before(self, lse: TradingCalendar) -> None:
        assert lse.next_trading_day(date(2023, 6, 15)) == date(2023, 6, 16)
        assert lse.previous_trading_day(date(2023, 6, 15)) == date(2023, 6, 14)

    def test_beyond_the_supported_range_raises(self, lse: TradingCalendar) -> None:
        with pytest.raises(CalendarRangeExhausted):
            lse.next_trading_day(lse.last_supported_date)
        with pytest.raises(CalendarRangeExhausted):
            lse.previous_trading_day(lse.first_supported_date)


class TestSessionsBetween:
    def test_hand_counted_month(self, lse: TradingCalendar) -> None:
        # June 2012 had 21 weekdays; the spring bank holiday (Mon 4th) and the Diamond
        # Jubilee holiday (Tue 5th) leave 19 sessions.
        sessions = lse.sessions_between(date(2012, 6, 1), date(2012, 6, 30))
        assert len(sessions) == 19
        assert sessions[0] == date(2012, 6, 1)
        assert sessions[1] == date(2012, 6, 6)
        assert sessions[-1] == date(2012, 6, 29)

    def test_hand_counted_week(self, lse: TradingCalendar) -> None:
        assert lse.sessions_between(date(2023, 6, 12), date(2023, 6, 18)) == (
            date(2023, 6, 12),
            date(2023, 6, 13),
            date(2023, 6, 14),
            date(2023, 6, 15),
            date(2023, 6, 16),
        )

    def test_both_endpoints_are_inclusive(self, lse: TradingCalendar) -> None:
        assert lse.sessions_between(date(2023, 6, 12), date(2023, 6, 12)) == (date(2023, 6, 12),)

    def test_endpoints_need_not_be_trading_days(self, lse: TradingCalendar) -> None:
        assert lse.sessions_between(date(2023, 6, 17), date(2023, 6, 18)) == ()

    def test_reversed_range_raises(self, lse: TradingCalendar) -> None:
        with pytest.raises(ValueError, match="after end"):
            lse.sessions_between(date(2023, 6, 30), date(2023, 6, 1))


class TestOutOfRange:
    def test_before_supported_range_raises_rather_than_guessing(self, lse: TradingCalendar) -> None:
        # A Monday in 1987 — weekday logic would happily call it a trading day.
        with pytest.raises(DateOutOfCalendarRange):
            lse.is_trading_day(date(1987, 10, 19))

    def test_after_supported_range_raises(self, lse: TradingCalendar) -> None:
        with pytest.raises(DateOutOfCalendarRange):
            lse.is_trading_day(date(2031, 1, 2))

    def test_every_query_is_bounds_checked(self, lse: TradingCalendar) -> None:
        outside = date(1987, 10, 19)
        inside = date(2023, 6, 15)
        with pytest.raises(DateOutOfCalendarRange):
            lse.is_half_day(outside)
        with pytest.raises(DateOutOfCalendarRange):
            lse.next_trading_day(outside)
        with pytest.raises(DateOutOfCalendarRange):
            lse.previous_trading_day(outside)
        with pytest.raises(DateOutOfCalendarRange):
            lse.sessions_between(outside, inside)
        with pytest.raises(DateOutOfCalendarRange):
            lse.sessions_between(inside, date(2031, 1, 2))

    def test_supported_range_is_fixed_not_relative_to_today(self, lse: TradingCalendar) -> None:
        # A range anchored to the current date would make the same historical query
        # answerable this year and out of range next year.
        assert lse.first_supported_date == date(2000, 1, 1)
        assert lse.last_supported_date == date(2030, 12, 31)


class TestMissingSessions:
    def test_absent_bar_on_a_trading_day_is_detectable(self, lse: TradingCalendar) -> None:
        # A security whose price history skips Wednesday 14 June 2023: the calendar side of
        # the QNT-019 gap check must report exactly that date, and not the weekend either
        # side of the window.
        observed = [
            date(2023, 6, 12),
            date(2023, 6, 13),
            date(2023, 6, 15),
            date(2023, 6, 16),
        ]
        assert lse.missing_sessions(observed, date(2023, 6, 12), date(2023, 6, 18)) == (
            date(2023, 6, 14),
        )

    def test_a_holiday_is_not_a_gap(self, lse: TradingCalendar) -> None:
        # The whole point: no bar on 5 June 2012 is the market being shut, not missing data.
        observed = [date(2012, 6, 1), date(2012, 6, 6), date(2012, 6, 7), date(2012, 6, 8)]
        assert lse.missing_sessions(observed, date(2012, 6, 1), date(2012, 6, 8)) == ()

    def test_complete_history_has_no_gaps(self, lse: TradingCalendar) -> None:
        sessions = lse.sessions_between(date(2023, 1, 1), date(2023, 12, 31))
        assert lse.missing_sessions(sessions, date(2023, 1, 1), date(2023, 12, 31)) == ()
