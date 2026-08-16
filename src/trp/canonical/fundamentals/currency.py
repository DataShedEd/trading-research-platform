"""Currency conversion for fundamentals — at query time, dated, and never at rest.

Shell is a UK-listed company that reports in US dollars and is quoted in pence. A value
factor that divides its dollar equity by a sterling market capitalisation is wrong by
roughly the exchange rate, and both numbers look entirely plausible. The fix is not to
convert on the way in: that bakes one rate, from one source, on one date, into the store,
destroys the figure the company actually filed, and makes every result irreproducible the
next time the FX source is revised. So:

* **storage is untouched.** Values sit in the currency they were reported in. Nothing in
  this module writes; QNT-024 stores what it is given, and a company changing reporting
  currency between periods simply has two periods in two currencies (that is not a
  revision — the QNT-022 key excludes currency — and needs no special handling here).
* **conversion happens here, on a query result, with an explicit ``as_of``.** Both the
  original ``currency``/``value`` and the ``converted_value`` come back in the same frame,
  alongside the rate, its date, its availability and its source, so any converted figure
  can be reproduced exactly.

**Conversion date rule (the convention, applied consistently to every statement).** The
rate used is the spot rate for the row's own ``period_end``. Stock items (balance sheet)
are a period-end snapshot, so period-end spot is the right rate by construction. Flow items
(income statement, cash flow) accrue across the period and are strictly better served by an
average rate over it — which needs a daily FX series we do not yet have. Rather than mix
conventions, both use period-end spot, which is reproducible from a single dated rate and
biases nothing in a systematic direction. When a daily series lands, average-rate
conversion for flow items is a deliberate, versioned change, not a silent improvement.

**FX availability (the point-in-time rule).** QNT-017's ``FxRateProvider`` carries no
availability of its own, so this module imposes one: the rate for date *d* is treated as
knowable only from 00:00 UTC on *d+1* — after *d*'s close. Erring late follows DEC-007's
spirit. A conversion whose ``as_of`` precedes that instant raises
:class:`FxRateNotYetAvailableError` and never reaches forward to a later rate; that guard
is unconditional, because ``strict`` governs missing data, not leakage.

**Rounding (DEC-005).** Arithmetic runs in a 60-digit local decimal context so no
intermediate is silently rounded by the ambient one, and the converted figure is quantised
exactly once, at the end, to six decimal places with banker's rounding — six places to
match the canonical store's ``Decimal(38, 6)``. Nothing round-trips through ``float``.
``fx_rate`` comes back as an exact decimal *string*: a Parquet-style fixed scale would
silently round a rate quoted to more places than the column allows, and a rounded audit
record is a useless audit record. ``Decimal(row["fx_rate"])`` recovers it exactly.

**Unit kinds.** A share count is not money. Rows whose canonical line item is a
``share_count`` or a ``ratio`` (per the QNT-021 taxonomy) are passed through unconverted
and flagged, because multiplying a share count by an FX rate is exactly the plausible wrong
number this platform exists to prevent. Line items absent from the taxonomy are treated as
currency amounts — the overwhelmingly common case — and labelled ``unknown`` so the
assumption is visible in the output rather than implied.
"""

from collections.abc import Sequence
from datetime import UTC, date, datetime, time, timedelta
from decimal import ROUND_HALF_EVEN, Decimal, localcontext

import polars as pl

from trp.canonical.fundamentals.taxonomy import LineItemTaxonomy, UnitKind, default_taxonomy
from trp.domain.reference import (
    FxRateProvider,
    FxRateUnavailableError,
    Money,
    ReferenceData,
    convert_with_fx,
    default_reference_data,
)

CONVERTED_EXPONENT = Decimal("0.000001")
"""Six decimal places — the canonical store's scale, so a converted figure and a stored one
are comparable without a second rounding decision."""

ROUNDING = ROUND_HALF_EVEN
ARITHMETIC_PRECISION = 60
CONVERSION_CONVENTION = "period-end spot"

_REQUIRED_COLUMNS = ("security_id", "statement", "line_item", "period_end", "currency", "value")

_UNKNOWN_UNIT_KIND = "unknown"


class FundamentalConversionError(Exception):
    """Base for conversion failures. Every one of them is loud by design: a fundamental
    that could not be converted must never leave here looking like one that was."""


class MissingColumnsError(FundamentalConversionError):
    def __init__(self, missing: Sequence[str]) -> None:
        self.missing = tuple(missing)
        super().__init__(
            f"frame is missing {list(missing)}: convert_fundamentals expects a result frame "
            "from trp.canonical.fundamentals.queries.fundamentals"
        )


class FxRateNotYetAvailableError(FundamentalConversionError):
    """The rate needed postdates the query's ``as_of``.

    Raised rather than substituting the nearest earlier rate, because that substitution is
    a research decision (how stale a rate may be) and not one this module gets to make
    silently. Widen ``as_of``, or convert a period whose rate was knowable.
    """

    def __init__(self, base: str, quote: str, on: date, available_at: datetime, as_of: datetime):
        self.base, self.quote, self.on = base, quote, on
        self.available_at, self.as_of = available_at, as_of
        super().__init__(
            f"the {base}/{quote} rate for {on} was not knowable at as_of {as_of.isoformat()}: "
            f"treated as available from {available_at.isoformat()} (close of {on}, err late). "
            "Reaching forward for it would be look-ahead"
        )


class MixedCurrencyError(FundamentalConversionError):
    """An aggregate spanning two currencies. Refused at the API rather than trusted to
    caller discipline: the sum of a dollar and a pound is not a number."""

    def __init__(self, currencies: Sequence[str]) -> None:
        self.currencies = tuple(currencies)
        super().__init__(
            f"rows span currencies {list(currencies)}: convert to one currency first "
            "(convert_fundamentals) — adding across currencies is arithmetic nonsense that "
            "type-checks perfectly"
        )


def fx_available_at(rate_date: date) -> datetime:
    """When a rate for ``rate_date`` becomes knowable: 00:00 UTC the following day.

    The conservative reading of "rates are published after the close". Documented and
    applied in one place so the assumption can be revisited when an FX source with real
    publication timestamps arrives.
    """
    return datetime.combine(rate_date + timedelta(days=1), time.min, tzinfo=UTC)


class _RecordingFx:
    """Passes rate requests through to the real provider and remembers the answer.

    The conversion itself stays in QNT-017's :func:`convert_with_fx` — one implementation
    of subunit-then-rate-then-subunit, not a second one here — but the audit record needs
    the rate that was used, and ``convert_with_fx`` returns only the money. Wrapping is
    cheaper and safer than asking the provider twice.
    """

    def __init__(self, inner: FxRateProvider) -> None:
        self._inner = inner
        self.rate_used: Decimal | None = None

    def rate(self, base: str, quote: str, on: date) -> Decimal:
        self.rate_used = self._inner.rate(base, quote, on)
        return self.rate_used


def _unit_kind(line_item: str, taxonomy: LineItemTaxonomy) -> str:
    item = taxonomy.get(line_item)
    return item.unit_kind.value if item is not None else _UNKNOWN_UNIT_KIND


def _is_monetary(unit_kind: str) -> bool:
    if unit_kind == _UNKNOWN_UNIT_KIND:
        return True
    return UnitKind(unit_kind).is_monetary


def _quantised(amount: Decimal) -> Decimal:
    return amount.quantize(CONVERTED_EXPONENT, rounding=ROUNDING)


def convert_fundamentals(
    frame: pl.DataFrame,
    *,
    to_currency: str,
    fx: FxRateProvider,
    as_of: datetime,
    fx_source: str | None = None,
    strict: bool = True,
    reference: ReferenceData | None = None,
    taxonomy: LineItemTaxonomy | None = None,
) -> pl.DataFrame:
    """Convert a fundamentals result frame into ``to_currency`` at query time.

    ``frame`` is what :func:`trp.canonical.fundamentals.queries.fundamentals` returns.
    Every input column survives untouched — the reported ``currency`` and ``value`` are
    still there beside the converted figure, which is the whole point — and these are
    added:

    ``target_currency``, ``converted_value`` (``Decimal``, null when not converted),
    ``fx_rate`` (exact decimal string, null when no cross-currency rate was needed),
    ``fx_rate_date``, ``fx_rate_available_at``, ``fx_source``, ``unit_kind``,
    ``converted`` (bool) and ``conversion_note`` (why not, when not).

    ``as_of`` must be the same ``as_of`` the frame was queried with; it bounds which FX
    rates may be used, per the module docstring's availability rule.

    ``strict`` (default true) decides what a *missing* rate does: raise, or produce a
    flagged null row that no caller can mistake for a converted one. It never softens the
    point-in-time guard — a rate that postdates ``as_of`` raises either way. There is no
    mode in which an unconverted value is passed off as converted.

    Rows in a currency that is the same money as the target (GBX against GBP) are scaled
    exactly by the QNT-017 unit policy and never touch the FX provider. Rows whose line
    item is not monetary (share counts, ratios) come back unconverted and flagged.
    """
    if as_of.tzinfo is None:
        raise ValueError("as_of must be timezone-aware (UTC)")
    missing = [column for column in _REQUIRED_COLUMNS if column not in frame.columns]
    if missing:
        raise MissingColumnsError(missing)

    data = reference if reference is not None else default_reference_data()
    items = taxonomy if taxonomy is not None else default_taxonomy()
    source_label = fx_source if fx_source is not None else type(fx).__qualname__
    target_major = data.major_currency_of(to_currency)

    converted_values: list[Decimal | None] = []
    rates: list[str | None] = []
    rate_dates: list[date | None] = []
    rate_available: list[datetime | None] = []
    unit_kinds: list[str] = []
    was_converted: list[bool] = []
    notes: list[str | None] = []

    for row in frame.iter_rows(named=True):
        line_item = str(row["line_item"])
        unit_kind = _unit_kind(line_item, items)
        unit_kinds.append(unit_kind)
        reported_currency = str(row["currency"])
        period_end: date = row["period_end"]

        if not _is_monetary(unit_kind):
            converted_values.append(None)
            rates.append(None)
            rate_dates.append(None)
            rate_available.append(None)
            was_converted.append(False)
            notes.append(f"{unit_kind} is not a monetary amount: never FX-converted, read `value`")
            continue

        source_major = data.major_currency_of(reported_currency)
        cross_currency = source_major.code != target_major.code
        rate_date = period_end if cross_currency else None
        if cross_currency:
            available_at = fx_available_at(period_end)
            if as_of < available_at:
                raise FxRateNotYetAvailableError(
                    source_major.code, target_major.code, period_end, available_at, as_of
                )

        money = Money(amount=row["value"], unit=reported_currency)
        recorder = _RecordingFx(fx)
        try:
            with localcontext() as context:
                context.prec = ARITHMETIC_PRECISION
                converted = convert_with_fx(
                    money, to_currency, on=period_end, provider=recorder, data=data
                )
                amount = _quantised(converted.amount)
        except FxRateUnavailableError as exc:
            if strict:
                exc.add_note(
                    f"while converting {row['security_id']} {line_item} "
                    f"period_end={period_end} from {reported_currency} to {to_currency} "
                    f"(as_of {as_of.isoformat()}, convention: {CONVERSION_CONVENTION})"
                )
                raise
            converted_values.append(None)
            rates.append(None)
            rate_dates.append(rate_date)
            rate_available.append(None)
            was_converted.append(False)
            notes.append(f"no rate: {exc}")
            continue

        converted_values.append(amount)
        rates.append(str(recorder.rate_used) if recorder.rate_used is not None else None)
        rate_dates.append(rate_date)
        rate_available.append(fx_available_at(period_end) if cross_currency else None)
        was_converted.append(True)
        notes.append(None)

    return frame.with_columns(
        pl.Series("target_currency", [to_currency] * frame.height, dtype=pl.Utf8),
        pl.Series("converted_value", converted_values, dtype=pl.Decimal(38, 6)),
        pl.Series("fx_rate", rates, dtype=pl.Utf8),
        pl.Series("fx_rate_date", rate_dates, dtype=pl.Date),
        pl.Series(
            "fx_rate_available_at",
            rate_available,
            dtype=pl.Datetime(time_unit="us", time_zone="UTC"),
        ),
        pl.Series(
            "fx_source",
            [source_label if c else None for c in was_converted],
            dtype=pl.Utf8,
        ),
        pl.Series("unit_kind", unit_kinds, dtype=pl.Utf8),
        pl.Series("converted", was_converted, dtype=pl.Boolean),
        pl.Series("conversion_note", notes, dtype=pl.Utf8),
    )


def require_single_currency(frame: pl.DataFrame, *, column: str = "currency") -> str:
    """The one currency these rows are in, or :class:`MixedCurrencyError`.

    The guard to call before any aggregate. It exists so that mixing currencies is an
    error at the API rather than a discipline the caller has to remember at 6pm.
    """
    if column not in frame.columns:
        raise MissingColumnsError([column])
    currencies = sorted({str(c) for c in frame.get_column(column).drop_nulls().to_list()})
    if len(currencies) > 1:
        raise MixedCurrencyError(currencies)
    if not currencies:
        raise FundamentalConversionError(
            "no rows: an aggregate has no currency to be stated in, which is not the same "
            "as being zero"
        )
    return currencies[0]


def total(
    frame: pl.DataFrame, *, value_column: str = "value", currency_column: str = "currency"
) -> Money:
    """Sum a value column, refusing to add across currencies.

    Returns :class:`~trp.domain.reference.Money` rather than a bare ``Decimal`` so the
    answer carries its unit onwards. To total a mixed-currency universe, run
    :func:`convert_fundamentals` first and total ``converted_value`` against
    ``target_currency``. Unit-kind coherence is the caller's: summing share counts is
    meaningful, summing share counts and revenue is not, and ``convert_fundamentals``
    labels every row's ``unit_kind`` so that is checkable.
    """
    currency = require_single_currency(frame, column=currency_column)
    if value_column not in frame.columns:
        raise MissingColumnsError([value_column])
    amounts = [a for a in frame.get_column(value_column).to_list() if a is not None]
    with localcontext() as context:
        context.prec = ARITHMETIC_PRECISION
        summed = sum(amounts, Decimal(0))
    return Money(amount=summed, unit=currency)
