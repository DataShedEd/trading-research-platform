"""Per-exchange trading calendars keyed by MIC.

Backed by the ``exchange-calendars`` library (DEC-010). This module is the only place that
library is touched: it maps MIC to library calendar code explicitly, bounds the supported
date range per exchange, and exposes dates rather than timestamps.

A trading day is a market-local ``date`` (DEC-005). Session open and close times are read
only to classify half days, and are never exposed or converted, so no session can be
shifted across a date boundary by a timezone conversion.

Querying outside an exchange's supported range raises `DateOutOfCalendarRange` rather than
falling back to weekday logic: a plausible-looking wrong answer here silently corrupts
return and rebalance arithmetic, which is the failure this module exists to prevent.
"""

from bisect import bisect_left, bisect_right
from collections.abc import Iterable, Mapping
from datetime import date, timedelta
from typing import Any

# exchange_calendars ships no py.typed marker, so its API is untyped to mypy. The ignore is
# scoped to this import; everything the library returns is converted to stdlib types here.
import exchange_calendars as xcals  # type: ignore[import-untyped]


class CalendarError(Exception):
    pass


class UnknownExchange(CalendarError):
    def __init__(self, mic: str) -> None:
        self.mic = mic
        super().__init__(
            f"no trading calendar for MIC {mic!r}; supported: {sorted(SUPPORTED_EXCHANGES)}"
        )


class DateOutOfCalendarRange(CalendarError):
    def __init__(self, mic: str, on: date, first: date, last: date) -> None:
        self.mic = mic
        self.on = on
        super().__init__(
            f"{on} is outside the supported range of the {mic} calendar ({first} to {last})"
        )


class CalendarRangeExhausted(CalendarError):
    """The answer exists but lies outside the supported range, so it is not returned."""

    def __init__(self, mic: str, on: date, direction: str) -> None:
        self.mic = mic
        self.on = on
        self.direction = direction
        super().__init__(
            f"the {direction} trading day relative to {on} falls outside the supported "
            f"range of the {mic} calendar"
        )


# MIC → exchange_calendars code, stated explicitly. The two coincide for these venues, but
# the library's codes are its own namespace and must not be assumed to be MICs.
_CALENDAR_CODES: Mapping[str, str] = {
    "XLON": "XLON",
    "XNYS": "XNYS",
    "XNAS": "XNAS",
}

SUPPORTED_EXCHANGES: frozenset[str] = frozenset(_CALENDAR_CODES)

# Supported range per exchange: deliberately bounded, and fixed rather than relative. LSE
# holiday data before roughly 2000 is patchy in every source (QNT-016 risks), and the
# library's own default range is anchored to today — which would make the same historical
# query answerable this year and out of range next year.
_SUPPORTED_RANGES: Mapping[str, tuple[date, date]] = {
    "XLON": (date(2000, 1, 1), date(2030, 12, 31)),
    "XNYS": (date(2000, 1, 1), date(2030, 12, 31)),
    "XNAS": (date(2000, 1, 1), date(2030, 12, 31)),
}

# The library calendar is built with padding either side of the supported range so that the
# supported range is strictly interior to it and our own bounds check is the only one that
# can fire.
_BUILD_PADDING = timedelta(days=400)


class TradingCalendar:
    """Trading days for one exchange over an explicitly bounded date range.

    Sessions for the supported range are materialised once at construction; all queries are
    lookups over that sorted tuple. Construct via `get_trading_calendar`, which caches one
    instance per MIC — `previous_trading_day` is called once per security per bar in the
    adjustment engine, and per-call construction would dominate its runtime.
    """

    def __init__(self, mic: str) -> None:
        if mic not in _CALENDAR_CODES:
            raise UnknownExchange(mic)
        self.mic = mic
        self.first_supported_date, self.last_supported_date = _SUPPORTED_RANGES[mic]
        calendar = xcals.get_calendar(
            _CALENDAR_CODES[mic],
            start=(self.first_supported_date - _BUILD_PADDING).isoformat(),
            end=(self.last_supported_date + _BUILD_PADDING).isoformat(),
        )
        self._sessions: tuple[date, ...] = tuple(
            session_date
            for session_date in (timestamp.date() for timestamp in calendar.sessions)
            if self.first_supported_date <= session_date <= self.last_supported_date
        )
        self._session_set: frozenset[date] = frozenset(self._sessions)
        self._half_days: frozenset[date] = self._derive_half_days(calendar)

    def _derive_half_days(self, calendar: Any) -> frozenset[date]:
        """Sessions shorter than the exchange's usual session length.

        Session length, not close time, is the criterion: it is invariant under daylight
        saving whereas the UTC close time is not, and it needs no timezone conversion.
        """
        durations = calendar.closes - calendar.opens
        usual = durations.mode()[0]
        return frozenset(
            short_date
            for short_date in (timestamp.date() for timestamp in durations.index[durations < usual])
            if short_date in self._session_set
        )

    def __repr__(self) -> str:
        return (
            f"TradingCalendar({self.mic!r}, "
            f"{self.first_supported_date}..{self.last_supported_date})"
        )

    def _check_supported(self, on: date) -> None:
        if not (self.first_supported_date <= on <= self.last_supported_date):
            raise DateOutOfCalendarRange(
                self.mic, on, self.first_supported_date, self.last_supported_date
            )

    def is_trading_day(self, on: date) -> bool:
        self._check_supported(on)
        return on in self._session_set

    def is_half_day(self, on: date) -> bool:
        """Whether `on` is a shortened session (an early close). Half days are trading days."""
        self._check_supported(on)
        return on in self._half_days

    def next_trading_day(self, on: date) -> date:
        """The first trading day strictly after `on`, skipping weekends and holidays."""
        self._check_supported(on)
        index = bisect_right(self._sessions, on)
        if index == len(self._sessions):
            raise CalendarRangeExhausted(self.mic, on, "next")
        return self._sessions[index]

    def previous_trading_day(self, on: date) -> date:
        """The last trading day strictly before `on`, skipping weekends and holidays."""
        self._check_supported(on)
        index = bisect_left(self._sessions, on)
        if index == 0:
            raise CalendarRangeExhausted(self.mic, on, "previous")
        return self._sessions[index - 1]

    def sessions_between(self, start: date, end: date) -> tuple[date, ...]:
        """Trading days from `start` to `end`, **inclusive of both endpoints**.

        Endpoints need not themselves be trading days.
        """
        self._check_supported(start)
        self._check_supported(end)
        if start > end:
            raise ValueError(f"start {start} is after end {end}")
        left = bisect_left(self._sessions, start)
        right = bisect_right(self._sessions, end)
        return self._sessions[left:right]

    def missing_sessions(
        self, observed: Iterable[date], start: date, end: date
    ) -> tuple[date, ...]:
        """Trading days in `[start, end]` with no observed date — candidate data gaps.

        The calendar half of the gap check consumed by QNT-019: it says which dates a
        security *should* have a bar for, and says nothing about why one is absent.
        """
        observed_dates = set(observed)
        return tuple(
            session
            for session in self.sessions_between(start, end)
            if session not in observed_dates
        )


_CACHE: dict[str, TradingCalendar] = {}


def get_trading_calendar(mic: str) -> TradingCalendar:
    """The cached calendar for `mic`. Raises `UnknownExchange` for an unsupported MIC."""
    if mic not in _CALENDAR_CODES:
        raise UnknownExchange(mic)
    calendar = _CACHE.get(mic)
    if calendar is None:
        calendar = TradingCalendar(mic)
        _CACHE[mic] = calendar
    return calendar
