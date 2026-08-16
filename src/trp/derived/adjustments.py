"""Adjustment factors derived from corporate actions. Raw prices are never touched.

Convention (backward-cumulative, latest = 1): for each security, the factor on the most
recent bar date is exactly 1 and factors for earlier dates accumulate the events between.
``adjusted = raw x split_factor`` gives the split-adjusted series;
``raw x split_factor x dividend_factor`` gives the total-return series. Standard forms:

- split factor for date ``d``: product over splits with ``ex_date > d`` of
  ``old_shares / new_shares`` (a 2-for-1 split halves all earlier prices);
- dividend factor for date ``d``: product over dividends with ``ex_date > d`` of
  ``1 - D / P``, where ``P`` is the raw close on the last bar before the ex-date,
  expressed post-split when a split shares the ex-date (split applies first — the
  documented composition order).

Arithmetic is exact ``Fraction`` throughout the derivation (Decimals convert exactly);
floats appear only via :func:`factors_to_float_frame`, the single analytics boundary.

Point-in-time: ``compute_adjustment_factors`` requires ``as_of`` and excludes actions
with ``available_at > as_of`` — a dividend the vendor published late cannot retroactively
change a backtest's returns.

Rights issues are **deliberately not adjusted** (DEC-009): affected securities are
flagged in ``warnings`` rather than quietly mis-adjusted.
"""

from collections import defaultdict
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal
from fractions import Fraction
from pathlib import Path

import polars as pl

from trp.domain.corporate_actions import CorporateAction, Dividend, RightsIssue, Split
from trp.domain.identifiers import SecurityId
from trp.domain.prices import DailyBar
from trp.domain.security import FrozenModel

# A dividend's previous close must be within this many calendar days of the ex-date;
# a larger gap means missing bars, and reaching further back would use a stale price.
# Refined by the trading calendar in QNT-016.
_MAX_PREV_CLOSE_GAP_DAYS = 7

_FACTOR_DECIMAL = pl.Decimal(precision=38, scale=18)
_FACTOR_SCALE = Decimal(1).scaleb(-18)

FACTOR_SCHEMA: dict[str, pl.DataType | type[pl.DataType]] = {
    "security_id": pl.Utf8,
    "trade_date": pl.Date,
    "split_num": pl.Int64,
    "split_den": pl.Int64,
    "split_factor": _FACTOR_DECIMAL,
    "dividend_factor": _FACTOR_DECIMAL,
}


class AdjustmentError(Exception):
    pass


class AdjustmentProvenance(FrozenModel):
    """What produced a factor set — enough to regenerate it (QUANT_PRINCIPLES §4)."""

    as_of: datetime
    bar_count: int
    action_count_applied: int
    special_dividends_applied: int
    actions_excluded_by_as_of: int
    latest_bar_ingested_at: datetime | None
    warnings: tuple[str, ...]


@dataclass(frozen=True)
class AdjustmentComputation:
    factors: pl.DataFrame  # FACTOR_SCHEMA
    exact: dict[tuple[SecurityId, date], tuple[Fraction, Fraction]]  # (split, dividend)
    provenance: AdjustmentProvenance


def _to_decimal(fraction: Fraction) -> Decimal:
    return (Decimal(fraction.numerator) / Decimal(fraction.denominator)).quantize(_FACTOR_SCALE)


def compute_adjustment_factors(
    bars: Sequence[DailyBar],
    actions: Sequence[CorporateAction],
    *,
    as_of: datetime,
) -> AdjustmentComputation:
    if as_of.tzinfo is None:
        raise ValueError("as_of must be timezone-aware (UTC)")

    known = [a for a in actions if a.available_at <= as_of]
    excluded = len(actions) - len(known)

    bars_by_security: dict[SecurityId, list[DailyBar]] = defaultdict(list)
    for bar in bars:
        bars_by_security[bar.security_id].append(bar)

    warnings: list[str] = []
    specials = 0
    applied = 0
    rows: list[dict[str, object]] = []
    exact: dict[tuple[SecurityId, date], tuple[Fraction, Fraction]] = {}

    for security_id, security_bars in bars_by_security.items():
        security_bars.sort(key=lambda b: b.trade_date)
        dates = [b.trade_date for b in security_bars]
        closes = {b.trade_date: b.close for b in security_bars}
        last = dates[-1]

        splits_by_ex: dict[date, Fraction] = defaultdict(lambda: Fraction(1))
        dividends_by_ex: dict[date, list[Dividend]] = defaultdict(list)
        for action in known:
            if action.security_id != security_id:
                continue
            if isinstance(action, RightsIssue):
                warnings.append(
                    f"security {security_id}: rights issue on {action.ex_date} NOT adjusted "
                    "(DEC-009) — treat adjusted series before that date with caution"
                )
                continue
            if action.ex_date > last:
                continue  # applies to no held bar; the latest-date-=1 convention ignores it
            if isinstance(action, Split):
                splits_by_ex[action.ex_date] *= action.ratio
                applied += 1
            elif isinstance(action, Dividend):
                dividends_by_ex[action.ex_date].append(action)
                applied += 1
                if action.special:
                    specials += 1

        event_dates = sorted(set(splits_by_ex) | set(dividends_by_ex), reverse=True)
        event_factors: list[tuple[date, Fraction, Fraction]] = []
        for ex in event_dates:
            split_part = (
                Fraction(1) / splits_by_ex[ex] if ex in splits_by_ex else Fraction(1)
            )  # old/new: a 2-for-1 split contributes 1/2 to earlier dates
            dividend_part = Fraction(1)
            if ex in dividends_by_ex:
                prev = _previous_close_date(dates, ex, security_id)
                # Post-split terms when a split shares the ex-date: split applies first.
                denominator = Fraction(closes[prev]) * (
                    Fraction(1) / splits_by_ex[ex] if ex in splits_by_ex else Fraction(1)
                )
                for dividend in dividends_by_ex[ex]:
                    dividend_part *= 1 - Fraction(dividend.amount) / denominator
            event_factors.append((ex, split_part, dividend_part))

        split_cumulative = Fraction(1)
        dividend_cumulative = Fraction(1)
        event_index = 0
        for trade_date in reversed(dates):
            while event_index < len(event_factors) and event_factors[event_index][0] > trade_date:
                _, split_part, dividend_part = event_factors[event_index]
                split_cumulative *= split_part
                dividend_cumulative *= dividend_part
                event_index += 1
            exact[(security_id, trade_date)] = (split_cumulative, dividend_cumulative)
            rows.append(
                {
                    "security_id": security_id,
                    "trade_date": trade_date,
                    "split_num": split_cumulative.numerator,
                    "split_den": split_cumulative.denominator,
                    "split_factor": _to_decimal(split_cumulative),
                    "dividend_factor": _to_decimal(dividend_cumulative),
                }
            )

    factors = pl.DataFrame(rows, schema=FACTOR_SCHEMA).sort(["security_id", "trade_date"])
    provenance = AdjustmentProvenance(
        as_of=as_of,
        bar_count=len(bars),
        action_count_applied=applied,
        special_dividends_applied=specials,
        actions_excluded_by_as_of=excluded,
        latest_bar_ingested_at=max((b.ingested_at for b in bars), default=None),
        warnings=tuple(warnings),
    )
    return AdjustmentComputation(factors=factors, exact=exact, provenance=provenance)


def _previous_close_date(dates: list[date], ex_date: date, security_id: SecurityId) -> date:
    candidates = [d for d in dates if d < ex_date]
    if not candidates:
        raise AdjustmentError(
            f"security {security_id}: no bar before ex-date {ex_date} to anchor the dividend yield"
        )
    prev = candidates[-1]
    if (ex_date - prev).days > _MAX_PREV_CLOSE_GAP_DAYS:
        raise AdjustmentError(
            f"security {security_id}: previous close {prev} is {(ex_date - prev).days} days "
            f"before ex-date {ex_date} — bars are missing; refusing to reach further back"
        )
    return prev


def adjusted_prices(bars: Sequence[DailyBar], computation: AdjustmentComputation) -> pl.DataFrame:
    """Per bar: raw close, split-adjusted close, and total-return-adjusted close."""
    rows = []
    for bar in bars:
        split, dividend = computation.exact[(bar.security_id, bar.trade_date)]
        close = Fraction(bar.close)
        rows.append(
            {
                "security_id": bar.security_id,
                "trade_date": bar.trade_date,
                "currency": bar.currency,
                "close_raw": bar.close,
                "close_split_adjusted": _to_decimal(close * split),
                "close_total_return": _to_decimal(close * split * dividend),
            }
        )
    schema: dict[str, pl.DataType | type[pl.DataType]] = {
        "security_id": pl.Utf8,
        "trade_date": pl.Date,
        "currency": pl.Utf8,
        "close_raw": pl.Decimal(precision=18, scale=6),
        "close_split_adjusted": _FACTOR_DECIMAL,
        "close_total_return": _FACTOR_DECIMAL,
    }
    return pl.DataFrame(rows, schema=schema).sort(["security_id", "trade_date"])


def total_returns(bars: Sequence[DailyBar], computation: AdjustmentComputation) -> pl.DataFrame:
    """Bar-over-bar total returns from the total-return-adjusted series, exact then quantised."""
    by_security: dict[SecurityId, list[DailyBar]] = defaultdict(list)
    for bar in bars:
        by_security[bar.security_id].append(bar)

    rows = []
    for security_id, security_bars in by_security.items():
        security_bars.sort(key=lambda b: b.trade_date)
        previous: Fraction | None = None
        for bar in security_bars:
            split, dividend = computation.exact[(security_id, bar.trade_date)]
            adjusted = Fraction(bar.close) * split * dividend
            if previous is not None:
                rows.append(
                    {
                        "security_id": security_id,
                        "trade_date": bar.trade_date,
                        "total_return": _to_decimal(adjusted / previous - 1),
                    }
                )
            previous = adjusted
    schema: dict[str, pl.DataType | type[pl.DataType]] = {
        "security_id": pl.Utf8,
        "trade_date": pl.Date,
        "total_return": _FACTOR_DECIMAL,
    }
    return pl.DataFrame(rows, schema=schema).sort(["security_id", "trade_date"])


def reconcile_provider_adjusted(
    bars: Sequence[DailyBar], computation: AdjustmentComputation
) -> pl.DataFrame:
    """Diagnostic: our total-return-adjusted close vs the provider's adjusted close.

    Disagreement is expected (providers treat specials differently); this report exists to
    surface it, never to tune our factors toward the provider's.
    """
    rows = []
    for bar in bars:
        if bar.provider_adjusted_close is None:
            continue
        split, dividend = computation.exact[(bar.security_id, bar.trade_date)]
        ours = Fraction(bar.close) * split * dividend
        theirs = Fraction(bar.provider_adjusted_close)
        rows.append(
            {
                "security_id": bar.security_id,
                "trade_date": bar.trade_date,
                "ours": _to_decimal(ours),
                "provider": bar.provider_adjusted_close,
                "relative_difference": _to_decimal(ours / theirs - 1),
            }
        )
    schema: dict[str, pl.DataType | type[pl.DataType]] = {
        "security_id": pl.Utf8,
        "trade_date": pl.Date,
        "ours": _FACTOR_DECIMAL,
        "provider": pl.Decimal(precision=18, scale=6),
        "relative_difference": _FACTOR_DECIMAL,
    }
    return pl.DataFrame(rows, schema=schema).sort(["security_id", "trade_date"])


def factors_to_float_frame(computation: AdjustmentComputation) -> pl.DataFrame:
    """THE Decimal→float boundary for vectorised analytics. The only sanctioned cast."""
    return computation.factors.with_columns(
        pl.col("split_factor").cast(pl.Float64),
        pl.col("dividend_factor").cast(pl.Float64),
    )


def write_adjustment_factors(computation: AdjustmentComputation, directory: Path) -> None:
    """Persist a factor set with its provenance. Refuses to overwrite: a new computation
    is a new factor set, and old sets referenced by research results stay untouched."""
    if directory.exists():
        raise AdjustmentError(f"{directory} already exists; factor sets are never overwritten")
    directory.mkdir(parents=True)
    computation.factors.write_parquet(directory / "factors.parquet")
    (directory / "provenance.json").write_text(computation.provenance.model_dump_json(indent=2))
