"""THE returns library: one definition of a return for factors, risk and backtests.

Everything downstream (momentum, risk statistics, performance) computes returns through
this module so that divergent conventions cannot hide errors. Definitions:

- **Price return**: split-adjusted close over the window. **Total return**: split- and
  dividend-adjusted (ordinary AND special dividends) under the standard **reinvestment
  convention** — each dividend is reinvested at the ex-date price, so a flat 1000p series
  paying 50p returns 1000/950 - 1 = 5.26%, not 5.00% — via the QNT-015 adjustment engine,
  which takes this engine's ``as_of``, so a corporate action published after ``as_of``
  cannot change any return computed here (QUANT_PRINCIPLES §1).
- **Windows are calendar months with a skip**: ``WindowSpec(months=12, skip_months=1)``
  is classic 12-1 momentum — the window runs from 12 months before ``end`` to 1 month
  before ``end``, endpoints resolved to the last bar ON OR BEFORE each date (both
  endpoints inclusive in that sense), no more than ``max_staleness_days`` older.
- **Missing-data policy** (explicit, the classic bias source): a window must contain at
  least ``min_coverage`` of the exchange calendar's expected sessions, or the result is
  ``INSUFFICIENT_DATA`` — a typed status, never a silently wrong number. Nothing is
  forward-filled across a delisting.
- **Delistings**: a security whose bars end mid-window returns through the event using
  known proceeds — cash consideration from a merger/acquisition record (converted to the
  quote unit exactly), or zero for a failure (-100%). Unknown proceeds are the typed
  ``DELISTED_NO_PROCEEDS`` status, never a silent truncation at the last print.
- **Units**: dividends are aligned to the bar quote unit before the dividend factor is
  computed — EODHD reports LSE dividends in GBP against GBX prices, and an unaligned
  ``D/P`` is wrong by exactly 100x. Non-sterling dividends that cannot be aligned without
  FX are skipped with a warning (price returns unaffected; FX wiring is QNT-023's
  interface, to be connected when a mixed-currency case matters).

Float arithmetic is appropriate here (derived layer, DEC-005); the Decimal boundary is
the canonical store and the adjustment engine's exact factors underneath.
"""

from collections import defaultdict
from collections.abc import Sequence
from datetime import date, datetime
from decimal import Decimal
from enum import StrEnum
from pathlib import Path
from typing import Self

import polars as pl
from pydantic import Field, model_validator

from trp.canonical.calendars import get_trading_calendar
from trp.derived.adjustments import AdjustmentComputation, compute_adjustment_factors
from trp.domain.corporate_actions import (
    CorporateAction,
    DelistingAction,
    Dividend,
    Merger,
)
from trp.domain.identifiers import SecurityId
from trp.domain.prices import DailyBar
from trp.domain.reference import ReferenceDataError, default_reference_data
from trp.domain.security import DelistingReason, FrozenModel, revalidated_copy


class ReturnBasis(StrEnum):
    PRICE = "price"
    TOTAL = "total"


class ReturnStatus(StrEnum):
    OK = "ok"
    INSUFFICIENT_DATA = "insufficient_data"
    DELISTED_NO_PROCEEDS = "delisted_no_proceeds"
    NO_DATA = "no_data"


class WindowSpec(FrozenModel):
    months: int = Field(gt=0)
    skip_months: int = Field(default=0, ge=0)

    @model_validator(mode="after")
    def _skip_inside_window(self) -> Self:
        if self.skip_months >= self.months:
            raise ValueError("skip_months must be smaller than months")
        return self

    def label(self) -> str:
        return f"{self.months}-{self.skip_months}"


class WindowReturn(FrozenModel):
    security_id: SecurityId
    end: date
    window: str
    basis: ReturnBasis
    status: ReturnStatus
    value: float | None = None
    start_bar: date | None = None
    end_bar: date | None = None
    observations: int = 0
    expected_sessions: int = 0
    used_delisting_proceeds: bool = False
    warnings: tuple[str, ...] = ()


def shift_months(day: date, months: int) -> date:
    """Calendar-month shift, clamping to the target month's last day (Jan 31 - 1m → Dec 31)."""
    month_index = day.year * 12 + (day.month - 1) + months
    year, month = divmod(month_index, 12)
    month += 1
    last_day = (date(year + (month == 12), (month % 12) + 1, 1) - date.resolution).day
    return date(year, month, min(day.day, last_day))


class ReturnsEngine:
    def __init__(
        self,
        bars: Sequence[DailyBar],
        actions: Sequence[CorporateAction],
        *,
        as_of: datetime,
        mic: str = "XLON",
        max_staleness_days: int = 15,
        min_coverage: float = 0.6,
    ) -> None:
        self._as_of = as_of
        self._calendar = get_trading_calendar(mic)
        self._max_staleness = max_staleness_days
        self._min_coverage = min_coverage
        self._warnings: dict[SecurityId, list[str]] = defaultdict(list)

        self._unit: dict[SecurityId, str] = {}
        for bar in bars:
            existing = self._unit.setdefault(bar.security_id, bar.currency)
            if existing != bar.currency:
                self._warnings[bar.security_id].append(
                    f"mixed quote units {existing}/{bar.currency}"
                )

        aligned = self._align_dividend_units(actions)
        self._computation: AdjustmentComputation = compute_adjustment_factors(
            bars, aligned, as_of=as_of
        )
        for warning in self._computation.provenance.warnings:
            for security_id in self._unit:
                if str(security_id) in warning:
                    self._warnings[security_id].append(warning)

        self._series: dict[SecurityId, list[tuple[date, float, float]]] = defaultdict(list)
        for bar in bars:
            split, dividend = self._computation.exact[(bar.security_id, bar.trade_date)]
            close = float(bar.close)
            self._series[bar.security_id].append(
                (bar.trade_date, close * float(split), close * float(split) * float(dividend))
            )
        for series in self._series.values():
            series.sort(key=lambda row: row[0])

        self._proceeds: dict[SecurityId, tuple[date, float | None]] = {}
        for action in actions:
            if action.available_at > as_of:
                continue
            if isinstance(action, Merger) and action.cash_amount is not None:
                self._proceeds[action.security_id] = (
                    action.ex_date,
                    self._cash_in_quote_unit(
                        action.security_id, action.cash_amount, action.cash_currency
                    ),
                )
            elif isinstance(action, DelistingAction):
                proceeds = 0.0 if action.reason is DelistingReason.FAILURE else None
                self._proceeds.setdefault(action.security_id, (action.ex_date, proceeds))

    def _cash_in_quote_unit(
        self, security_id: SecurityId, amount: Decimal, currency: str | None
    ) -> float | None:
        unit = self._unit.get(security_id)
        if unit is None or currency is None:
            return None
        if currency == unit:
            return float(amount)
        try:
            return float(default_reference_data().convert(amount, currency, unit))
        except ReferenceDataError:
            self._warnings[security_id].append(
                f"cash proceeds in {currency} not convertible to quote unit {unit}"
            )
            return None

    def _align_dividend_units(self, actions: Sequence[CorporateAction]) -> list[CorporateAction]:
        aligned: list[CorporateAction] = []
        for action in actions:
            if not isinstance(action, Dividend):
                aligned.append(action)
                continue
            unit = self._unit.get(action.security_id)
            if unit is None or action.currency == unit:
                aligned.append(action)
                continue
            try:
                converted = default_reference_data().convert(action.amount, action.currency, unit)
            except ReferenceDataError:
                self._warnings[action.security_id].append(
                    f"dividend {action.ex_date} in {action.currency} not alignable to "
                    f"{unit}: EXCLUDED from total returns (price returns unaffected)"
                )
                continue
            aligned.append(revalidated_copy(action, amount=converted, currency=unit))
        return aligned

    def _bar_on_or_before(
        self, security_id: SecurityId, day: date, basis: ReturnBasis
    ) -> tuple[date, float] | None:
        candidates = [row for row in self._series.get(security_id, []) if row[0] <= day]
        if not candidates:
            return None
        bar_date, price_basis, total_basis = candidates[-1]
        if (day - bar_date).days > self._max_staleness:
            return None
        return bar_date, (price_basis if basis is ReturnBasis.PRICE else total_basis)

    def window_return(
        self,
        security_id: SecurityId,
        end: date,
        window: WindowSpec,
        basis: ReturnBasis = ReturnBasis.TOTAL,
    ) -> WindowReturn:
        warnings = tuple(self._warnings.get(security_id, ()))
        series = self._series.get(security_id, [])
        if not series:
            return self._result(security_id, end, window, basis, ReturnStatus.NO_DATA, warnings)

        window_end = shift_months(end, -window.skip_months)
        window_start = shift_months(end, -window.months)
        start = self._bar_on_or_before(security_id, window_start, basis)
        if start is None:
            return self._result(
                security_id, end, window, basis, ReturnStatus.INSUFFICIENT_DATA, warnings
            )

        last_bar = series[-1][0]
        used_proceeds = False
        finish = self._bar_on_or_before(security_id, window_end, basis)
        if finish is None:
            delisting = self._proceeds.get(security_id)
            if last_bar < window_end and delisting is not None:
                event_date, proceeds = delisting
                if proceeds is None:
                    return self._result(
                        security_id,
                        end,
                        window,
                        basis,
                        ReturnStatus.DELISTED_NO_PROCEEDS,
                        warnings,
                    )
                # Latest-date factors are 1 by convention, so proceeds at the event
                # need no further adjustment; a failure's zero proceeds give -100%.
                finish = (min(event_date, window_end), proceeds)
                used_proceeds = True
            else:
                return self._result(
                    security_id, end, window, basis, ReturnStatus.INSUFFICIENT_DATA, warnings
                )

        start_bar, start_value = start
        end_bar, end_value = finish
        if start_value <= 0 or end_bar <= start_bar:
            return self._result(
                security_id, end, window, basis, ReturnStatus.INSUFFICIENT_DATA, warnings
            )

        expected = len(self._calendar.sessions_between(start_bar, end_bar))
        observed = sum(1 for row in series if start_bar <= row[0] <= end_bar)
        if not used_proceeds and expected and observed / expected < self._min_coverage:
            return self._result(
                security_id,
                end,
                window,
                basis,
                ReturnStatus.INSUFFICIENT_DATA,
                warnings,
                observations=observed,
                expected_sessions=expected,
            )

        return WindowReturn(
            security_id=security_id,
            end=end,
            window=window.label(),
            basis=basis,
            status=ReturnStatus.OK,
            value=end_value / start_value - 1.0,
            start_bar=start_bar,
            end_bar=end_bar,
            observations=observed,
            expected_sessions=expected,
            used_delisting_proceeds=used_proceeds,
            warnings=warnings,
        )

    def _result(
        self,
        security_id: SecurityId,
        end: date,
        window: WindowSpec,
        basis: ReturnBasis,
        status: ReturnStatus,
        warnings: tuple[str, ...],
        observations: int = 0,
        expected_sessions: int = 0,
    ) -> WindowReturn:
        return WindowReturn(
            security_id=security_id,
            end=end,
            window=window.label(),
            basis=basis,
            status=status,
            observations=observations,
            expected_sessions=expected_sessions,
            warnings=warnings,
        )

    def cross_section(
        self,
        security_ids: Sequence[SecurityId],
        end: date,
        window: WindowSpec,
        basis: ReturnBasis = ReturnBasis.TOTAL,
    ) -> pl.DataFrame:
        rows = [
            self.window_return(sid, end, window, basis).model_dump(mode="python")
            for sid in security_ids
        ]
        for row in rows:
            row["warnings"] = "; ".join(row["warnings"])
        return pl.DataFrame(rows)


def write_returns(frame: pl.DataFrame, directory: Path, *, as_of: datetime) -> None:
    """Persist a computed return set with its provenance; never overwrites."""
    if directory.exists():
        raise FileExistsError(f"{directory} exists; return sets are never overwritten")
    directory.mkdir(parents=True)
    frame.write_parquet(directory / "returns.parquet")
    (directory / "provenance.txt").write_text(f"as_of: {as_of.isoformat()}\n")
