"""Fundamental factor transforms (QNT-045/046): quality and value from PIT statements.

Everything here resolves fundamentals through the QNT-025 as-of choke point — the only
read path — so a value computed at date t can only use statements whose (possibly
DEC-007-imputed) ``available_at`` precedes t. Definitions name their line items in
configuration; these transforms contain arithmetic and refusal rules, never mappings.

Statuses (typed, never a NaN or an infinity):
- ``ok`` — computed.
- ``no_data`` — no reporting period has every required item available at t.
- ``not_meaningful`` — the period exists but the metric's refusal rule fired (negative
  equity book value, non-positive EBITDA under a debt multiple, non-positive enterprise
  value...). The row says WHY in ``warnings``.
- ``insufficient_data`` — a trailing-window metric with too few periods.

Period consistency: each security uses its LATEST reporting period for which every
required item is present — a consistent statement snapshot, never a mix of period ends.
Balance-sheet stocks against income flows use that same snapshot (period-end balances,
not averages), stated here once rather than assumed per definition.

Currency: within-statement ratios need no conversion (numerator and denominator share
the filing currency; a mixed-currency snapshot is refused). Market-value metrics convert
the fundamental to GBP at the dated FX rate on or before t (``trp.canonical.fx``) and
build market capitalisation from the raw GBX close on or before t times the shares
outstanding available at t.

Sector honesty: leverage and several margins are not meaningful for financial-sector
issuers, and the platform has no sector reference data yet. Until it does, that
exclusion CANNOT be applied here; the catalogue records the limitation and composite
work (QNT-048) must not lean on those metrics across financials.
"""

from bisect import bisect_right
from collections import defaultdict
from datetime import date

import polars as pl

from trp.canonical.fundamentals.queries import fundamentals
from trp.canonical.fx import FxError, FxRates
from trp.domain.fundamentals import PeriodType
from trp.domain.identifiers import SecurityId
from trp.factors.compute import ComputeContext, register_transform

_SCHEMA: dict[str, pl.DataType | type[pl.DataType]] = {
    "security_id": pl.Utf8,
    "status": pl.Utf8,
    "value": pl.Float64,
    "warnings": pl.List(pl.Utf8),
}

OK = "ok"
NO_DATA = "no_data"
NOT_MEANINGFUL = "not_meaningful"
INSUFFICIENT = "insufficient_data"


def _row(security_id: SecurityId, status: str, value: float | None, *warnings: str) -> dict:  # type: ignore[type-arg]
    return {
        "security_id": str(security_id),
        "status": status,
        "value": value,
        "warnings": list(warnings),
    }


def _frame(rows: list[dict]) -> pl.DataFrame:  # type: ignore[type-arg]
    return pl.DataFrame(rows, schema=_SCHEMA)


class Snapshot:
    """Per security: the latest reporting period holding every required item."""

    def __init__(self, values: dict[str, float], currency: str, period_end: date) -> None:
        self.values = values
        self.currency = currency
        self.period_end = period_end


def latest_snapshots(
    context: ComputeContext, items: list[str], *, period_type: PeriodType = PeriodType.ANNUAL
) -> dict[SecurityId, Snapshot | str]:
    """The consistent-snapshot resolver. Value is a Snapshot, or a warning string when
    no period qualifies (mixed currencies inside a period also disqualify it)."""
    if context.fundamentals_root is None:
        return dict.fromkeys(context.security_ids, "no fundamentals_root on the compute context")
    frame = fundamentals(
        context.fundamentals_root,
        [str(s) for s in context.security_ids],
        items,
        as_of=context.as_of,
        period_type=period_type,
    )
    by_security: dict[str, dict[date, dict[str, tuple[float, str]]]] = defaultdict(
        lambda: defaultdict(dict)
    )
    for row in frame.iter_rows(named=True):
        by_security[row["security_id"]][row["period_end"]][row["line_item"]] = (
            float(row["value"]),
            row["currency"],
        )
    out: dict[SecurityId, Snapshot | str] = {}
    for security_id in context.security_ids:
        periods = by_security.get(str(security_id), {})
        chosen: Snapshot | str = f"no {period_type.value} period with all of {items}"
        for period_end in sorted(periods, reverse=True):
            period = periods[period_end]
            if not all(item in period for item in items):
                continue
            currencies = {period[item][1] for item in items}
            if len(currencies) != 1:
                chosen = f"mixed currencies {sorted(currencies)} in period {period_end}"
                continue
            chosen = Snapshot(
                {item: period[item][0] for item in items}, currencies.pop(), period_end
            )
            break
        out[security_id] = chosen
    return out


def trailing_annual_values(
    context: ComputeContext, item: str, periods: int
) -> dict[SecurityId, list[float]]:
    """The last ``periods`` ANNUAL values of one item per security, oldest first."""
    if context.fundamentals_root is None:
        return {sid: [] for sid in context.security_ids}
    frame = fundamentals(
        context.fundamentals_root,
        [str(s) for s in context.security_ids],
        [item],
        as_of=context.as_of,
        period_type=PeriodType.ANNUAL,
    )
    series: dict[str, list[tuple[date, float]]] = defaultdict(list)
    for row in frame.iter_rows(named=True):
        series[row["security_id"]].append((row["period_end"], float(row["value"])))
    return {
        sid: [v for _d, v in sorted(series.get(str(sid), []))[-periods:]]
        for sid in context.security_ids
    }


def _params_items(parameters: dict[str, object], key: str) -> list[str]:
    raw = parameters.get(key, [])
    return [str(x) for x in raw] if isinstance(raw, list) else []


@register_transform("fundamental_ratio")
def _fundamental_ratio(context: ComputeContext, parameters: dict[str, object]) -> pl.DataFrame:
    """(sum(numerator) - sum(numerator_minus)) / sum(denominator), from one consistent
    statement snapshot. ``require_positive_denominator`` (default true) refuses zero or
    negative denominators as not_meaningful; set false only for denominators whose sign
    is itself meaningful."""
    numerator = _params_items(parameters, "numerator")
    numerator_minus = _params_items(parameters, "numerator_minus")
    denominator = _params_items(parameters, "denominator")
    require_positive = bool(parameters.get("require_positive_denominator", True))
    items = [*numerator, *numerator_minus, *denominator]
    snapshots = latest_snapshots(context, items)
    rows = []
    for security_id in context.security_ids:
        snapshot = snapshots[security_id]
        if isinstance(snapshot, str):
            rows.append(_row(security_id, NO_DATA, None, snapshot))
            continue
        den = sum(snapshot.values[i] for i in denominator)
        if require_positive and den <= 0:
            rows.append(_row(security_id, NOT_MEANINGFUL, None, f"denominator {den:.4g} <= 0"))
            continue
        if den == 0:
            rows.append(_row(security_id, NOT_MEANINGFUL, None, "denominator is zero"))
            continue
        num = sum(snapshot.values[i] for i in numerator) - sum(
            snapshot.values[i] for i in numerator_minus
        )
        rows.append(_row(security_id, OK, num / den))
    return _frame(rows)


@register_transform("roic")
def _roic(context: ComputeContext, parameters: dict[str, object]) -> pl.DataFrame:
    """NOPAT / invested capital: ebit x (1 - effective tax rate) over
    (total_equity + net_debt), all from one snapshot. Effective tax = tax_expense /
    pre_tax_profit clamped to [0, 1]; a non-positive pre-tax profit means no shield to
    estimate and uses 0 (documented). Invested capital <= 0 is not_meaningful."""
    items = ["ebit", "tax_expense", "pre_tax_profit", "total_equity", "net_debt"]
    snapshots = latest_snapshots(context, items)
    rows = []
    for security_id in context.security_ids:
        snapshot = snapshots[security_id]
        if isinstance(snapshot, str):
            rows.append(_row(security_id, NO_DATA, None, snapshot))
            continue
        values = snapshot.values
        invested = values["total_equity"] + values["net_debt"]
        if invested <= 0:
            rows.append(
                _row(security_id, NOT_MEANINGFUL, None, f"invested capital {invested:.4g} <= 0")
            )
            continue
        pre_tax = values["pre_tax_profit"]
        tax_rate = min(max(values["tax_expense"] / pre_tax, 0.0), 1.0) if pre_tax > 0 else 0.0
        rows.append(_row(security_id, OK, values["ebit"] * (1 - tax_rate) / invested))
    return _frame(rows)


@register_transform("earnings_stability")
def _earnings_stability(context: ComputeContext, parameters: dict[str, object]) -> pl.DataFrame:
    """Negative coefficient of variation of the trailing annual series (stable earners
    score high). Below ``min_periods`` reported years -> insufficient_data; a mean near
    zero has no meaningful scale -> not_meaningful."""
    item = str(parameters.get("item", "net_income"))
    periods = int(parameters.get("periods", 5))  # type: ignore[call-overload]
    min_periods = int(parameters.get("min_periods", 4))  # type: ignore[call-overload]
    trailing = trailing_annual_values(context, item, periods)
    rows = []
    for security_id in context.security_ids:
        values = trailing[security_id]
        if len(values) < min_periods:
            rows.append(
                _row(security_id, INSUFFICIENT, None, f"{len(values)} periods < {min_periods}")
            )
            continue
        mean = sum(values) / len(values)
        if abs(mean) < 1e-6:
            rows.append(_row(security_id, NOT_MEANINGFUL, None, "mean earnings ~ zero"))
            continue
        variance = sum((v - mean) ** 2 for v in values) / (len(values) - 1)
        rows.append(_row(security_id, OK, -((variance**0.5) / abs(mean))))
    return _frame(rows)


# ------------------------------------------------------------------ market-value side


def _close_gbp_on_or_before(
    context: ComputeContext, security_id: SecurityId
) -> tuple[date, float] | None:
    series = sorted(
        (bar.trade_date, bar.close, bar.currency)
        for bar in context.bars
        if bar.security_id == security_id
    )
    dates = [d for d, _c, _u in series]
    index = bisect_right(dates, context.end)
    if index == 0:
        return None
    trade_date, close, unit = series[index - 1]
    value = float(close) / 100 if unit == "GBX" else float(close)
    return trade_date, value


@register_transform("market_value_yield")
def _market_value_yield(context: ComputeContext, parameters: dict[str, object]) -> pl.DataFrame:
    """(fundamental in GBP) / (market value in GBP), point-in-time on both sides.

    Market cap = raw GBX close on or before t / 100 x shares_outstanding available at t.
    Enterprise value adds net_debt (converted at the dated FX rate). ``negate`` flips the
    numerator's sign (outflow-negative items reported as positive yields). A non-positive
    market value or denominator refuses as not_meaningful; a missing or stale FX rate
    refuses as no_data with the reason."""
    numerator = _params_items(parameters, "numerator")
    denominator_kind = str(parameters.get("denominator", "market_cap"))
    negate = bool(parameters.get("negate", False))
    require_positive_numerator_base = parameters.get("not_meaningful_when_negative")
    items = [*numerator, "shares_outstanding"]
    if denominator_kind == "enterprise_value":
        items.append("net_debt")
    snapshots = latest_snapshots(context, items)
    fx = FxRates(context.fx_root) if context.fx_root is not None else None
    rows = []
    for security_id in context.security_ids:
        snapshot = snapshots[security_id]
        if isinstance(snapshot, str):
            rows.append(_row(security_id, NO_DATA, None, snapshot))
            continue
        priced = _close_gbp_on_or_before(context, security_id)
        if priced is None:
            rows.append(_row(security_id, NO_DATA, None, "no close on or before t"))
            continue
        _trade_date, price_gbp = priced
        shares = snapshot.values["shares_outstanding"]
        if shares <= 0:
            rows.append(_row(security_id, NOT_MEANINGFUL, None, "non-positive share count"))
            continue
        market_cap = price_gbp * shares
        try:
            if snapshot.currency == "GBP":
                convert = 1.0
            elif fx is None:
                rows.append(_row(security_id, NO_DATA, None, "no fx_root for non-GBP statements"))
                continue
            else:
                convert = fx.to_gbp(1.0, snapshot.currency, context.end)
        except FxError as error:
            rows.append(_row(security_id, NO_DATA, None, str(error)))
            continue
        numerator_value = sum(snapshot.values[i] for i in numerator) * convert
        if negate:
            numerator_value = -numerator_value
        if require_positive_numerator_base is not None and numerator_value < 0:
            rows.append(
                _row(
                    security_id,
                    NOT_MEANINGFUL,
                    None,
                    str(require_positive_numerator_base),
                )
            )
            continue
        if denominator_kind == "market_cap":
            denominator_value = market_cap
        elif denominator_kind == "enterprise_value":
            denominator_value = market_cap + snapshot.values["net_debt"] * convert
        else:
            rows.append(_row(security_id, NO_DATA, None, f"unknown denominator {denominator_kind}"))
            continue
        if denominator_value <= 0:
            rows.append(
                _row(
                    security_id,
                    NOT_MEANINGFUL,
                    None,
                    f"{denominator_kind} {denominator_value:.4g} <= 0",
                )
            )
            continue
        rows.append(_row(security_id, OK, numerator_value / denominator_value))
    return _frame(rows)
