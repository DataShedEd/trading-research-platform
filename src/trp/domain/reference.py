"""Exchange and currency reference data, and the GBX/GBP quotation-unit policy.

LSE ordinaries are quoted in pence (GBX) while dividends, market capitalisation and
fundamentals for the same company are usually stated in pounds (GBP). Combining the two
without conversion produces a value wrong by exactly one hundred — a ratio that still
looks like a plausible number, which is why the bug survives inspection. This module makes
the quotation unit explicit data and makes every conversion explicit code:

* a quotation subunit's relationship to its major currency is **data** in the reference
  file (``units_per_major``), never a special case in conversion code;
* conversion between a subunit and its major currency is an exact ``Decimal`` decimal-point
  shift (DEC-005) — no float, no division, no rounding step, whatever the arithmetic
  context precision;
* conversion between unrelated currencies raises ``UnrelatedCurrencyError`` pointing at
  ``FxRateProvider`` rather than returning the amount unchanged;
* ``Money`` refuses to add, subtract or divide across differing units, so a GBX price and a
  GBP dividend cannot silently meet inside a factor computation.

Reference data is versioned repository content reviewed on change, not a live lookup: MICs
are retired and exchanges rename, and a backtest must be reproducible against the file as it
stood. See docs/DATA_MODEL.md.
"""

from datetime import date
from decimal import Decimal
from functools import cache
from importlib.resources import files
from pathlib import Path
from typing import Protocol, Self, runtime_checkable
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from pydantic import Field, field_validator, model_validator

from trp.domain.security import FrozenModel

_REFERENCE_DATA_DIR = "reference_data"
_REFERENCE_DATA_FILE = "markets.json"


class ReferenceDataError(Exception):
    """Base for reference-data and unit-conversion failures."""


class UnknownExchangeError(ReferenceDataError):
    def __init__(self, mic: str, known: tuple[str, ...]) -> None:
        self.mic = mic
        super().__init__(f"no exchange with MIC {mic!r} in reference data (known: {list(known)})")


class UnknownCurrencyError(ReferenceDataError):
    def __init__(self, code: str, known: tuple[str, ...]) -> None:
        self.code = code
        super().__init__(f"no currency {code!r} in reference data (known: {list(known)})")


class UnrelatedCurrencyError(ReferenceDataError):
    """Asked to convert between currencies that are not the same money.

    Deliberately not recoverable by unit arithmetic: GBX and GBP are the same money in
    different units, GBP and USD are not. Crossing the second boundary needs a rate for a
    specific date — see ``FxRateProvider`` and ``convert_with_fx``.
    """

    def __init__(self, from_unit: str, to_unit: str) -> None:
        self.from_unit = from_unit
        self.to_unit = to_unit
        super().__init__(
            f"cannot convert {from_unit} to {to_unit} by unit scaling: they are different "
            f"currencies, not a quotation subunit and its major currency. Use an "
            f"FxRateProvider (trp.domain.reference.FxRateProvider) with an explicit date, "
            f"e.g. convert_with_fx(money, {to_unit!r}, on=..., provider=...)"
        )


class CurrencyMismatchError(ReferenceDataError):
    """Arithmetic attempted across two different quotation units.

    Raised even when the units are related (GBX and GBP): conversion is always explicit, so
    the caller states which unit the result is in rather than inheriting whichever operand
    happened to come first.
    """

    def __init__(self, left: str, right: str, operation: str) -> None:
        super().__init__(
            f"cannot {operation} {left} and {right}: convert explicitly first "
            f"(Money.converted_to) — mixing quotation units silently is a hundredfold error"
        )


class FxRateUnavailableError(ReferenceDataError):
    """No FX rate for this pair on this date.

    The error an ``FxRateProvider`` raises rather than substituting a nearby date's rate,
    an inverse, or 1.0. Point-in-time correctness means a missing rate is missing.
    """

    def __init__(self, base: str, quote: str, on: date) -> None:
        self.base = base
        self.quote = quote
        self.on = on
        super().__init__(f"no {base}/{quote} rate available for {on}")


def _decimal_exponent(amount: Decimal) -> int:
    exponent = amount.as_tuple().exponent
    if not isinstance(exponent, int):  # NaN, sNaN or Infinity
        raise ValueError(f"{amount!r} is not a finite Decimal; monetary amounts must be finite")
    return exponent


def _shift_point(amount: Decimal, places: int) -> Decimal:
    """Move ``amount``'s decimal point ``places`` digits left (negative) or right (positive).

    Exact by construction: only the exponent changes, so no digit is lost regardless of the
    active decimal context's precision. ``Decimal("1234.5") / 100`` would round a value with
    more significant digits than the context allows; this cannot.
    """
    sign, digits, _ = amount.as_tuple()
    return Decimal((sign, digits, _decimal_exponent(amount) + places))


def _power_of_ten(value: int) -> int:
    """The exponent ``n`` with ``10**n == value``, or ValueError."""
    remainder, exponent = value, 0
    while remainder % 10 == 0 and remainder > 0:
        remainder //= 10
        exponent += 1
    if remainder != 1:
        raise ValueError(f"{value} is not a power of ten")
    return exponent


class Currency(FrozenModel):
    """A currency, or a quotation subunit of one.

    ``minor_unit`` is the ISO 4217 exponent — the number of decimal places in which the
    currency *settles* (GBP 2, JPY 0). It is not a quotation precision: LSE quotes half
    pence, so a GBX price legitimately carries a decimal even though pence do not subdivide
    for settlement.

    ``quotation_subunit_of`` + ``units_per_major`` make GBX-is-a-hundredth-of-GBP a fact in
    the reference file rather than a branch in conversion code. The factor must be a power
    of ten so that conversion is a decimal-point shift and therefore exact.
    """

    code: str = Field(pattern=r"^[A-Z]{3}$", description="ISO 4217, or GBX for pence sterling")
    name: str = Field(min_length=1)
    minor_unit: int = Field(ge=0, le=4, description="ISO 4217 exponent (settlement, not quoting)")
    quotation_subunit_of: str | None = Field(
        default=None, pattern=r"^[A-Z]{3}$", description="the major currency this unit quotes"
    )
    units_per_major: int | None = Field(
        default=None, gt=1, description="exact integer power of ten, e.g. 100 pence per pound"
    )

    @model_validator(mode="after")
    def _subunit_facts_are_complete(self) -> Self:
        if (self.quotation_subunit_of is None) != (self.units_per_major is None):
            raise ValueError(
                f"currency {self.code}: quotation_subunit_of and units_per_major must be "
                "given together — a subunit without a factor cannot be converted"
            )
        if self.units_per_major is not None:
            if self.quotation_subunit_of == self.code:
                raise ValueError(f"currency {self.code} cannot be a quotation subunit of itself")
            try:
                _power_of_ten(self.units_per_major)
            except ValueError as exc:
                raise ValueError(
                    f"currency {self.code}: units_per_major={self.units_per_major} must be a "
                    "power of ten so conversion is an exact decimal shift"
                ) from exc
        return self

    @property
    def is_quotation_subunit(self) -> bool:
        return self.quotation_subunit_of is not None

    @property
    def decimal_places_to_major(self) -> int:
        """Digits to shift left to reach the major currency (2 for GBX, 0 for a major)."""
        return 0 if self.units_per_major is None else _power_of_ten(self.units_per_major)


class Exchange(FrozenModel):
    """A trading venue's reference data.

    ``quotation_unit`` is what prices print in and ``trading_currency`` is what the money
    actually is: for XLON those differ (GBX vs GBP), which is the whole point of the record.
    ``timezone`` is stored for future intraday work and for mapping market-local dates to
    UTC instants; Milestone 1 is date-only and nothing depends on it yet.
    """

    mic: str = Field(pattern=r"^[A-Z0-9]{4}$", description="ISO 10383 market identifier code")
    name: str = Field(min_length=1)
    country: str = Field(pattern=r"^[A-Z]{2}$", description="ISO 3166-1 alpha-2")
    timezone: str = Field(min_length=1, description="IANA zone, e.g. Europe/London")
    trading_currency: str = Field(pattern=r"^[A-Z]{3}$", description="the currency money is in")
    quotation_unit: str = Field(pattern=r"^[A-Z]{3}$", description="the unit prices print in")

    @field_validator("timezone")
    @classmethod
    def _timezone_is_a_real_iana_zone(cls, value: str) -> str:
        try:
            ZoneInfo(value)
        except (ZoneInfoNotFoundError, ValueError) as exc:
            raise ValueError(f"{value!r} is not an IANA timezone") from exc
        return value

    @property
    def quotes_in_subunit(self) -> bool:
        return self.quotation_unit != self.trading_currency


class ReferenceData(FrozenModel):
    """The loaded reference file: currencies, exchanges, and the conversions between units.

    Cross-record invariants are enforced at construction — every currency an exchange names
    exists, MICs and codes are unique, and an exchange that quotes in a subunit quotes in a
    subunit *of its own trading currency*. A file that says XLON trades GBP and quotes in
    US cents is rejected rather than loaded and half-used.
    """

    schema_version: int = Field(default=1, ge=1)
    notes: str = ""
    currencies: tuple[Currency, ...] = Field(min_length=1)
    exchanges: tuple[Exchange, ...] = Field(min_length=1)

    @model_validator(mode="after")
    def _records_are_unique_and_referentially_whole(self) -> Self:
        codes = [c.code for c in self.currencies]
        if len(set(codes)) != len(codes):
            raise ValueError(f"duplicate currency codes: {sorted(set(codes))}")
        mics = [e.mic for e in self.exchanges]
        if len(set(mics)) != len(mics):
            raise ValueError(f"duplicate exchange MICs: {sorted(set(mics))}")

        known = {c.code: c for c in self.currencies}
        for currency in self.currencies:
            major = currency.quotation_subunit_of
            if major is not None:
                if major not in known:
                    raise ValueError(
                        f"currency {currency.code} quotes {major}, which is not defined"
                    )
                if known[major].is_quotation_subunit:
                    raise ValueError(
                        f"currency {currency.code} quotes {major}, which is itself a subunit; "
                        "chained subunits are not supported"
                    )
        for venue in self.exchanges:
            for label, code in (
                ("trading_currency", venue.trading_currency),
                ("quotation_unit", venue.quotation_unit),
            ):
                if code not in known:
                    raise ValueError(f"exchange {venue.mic}: {label} {code} is not defined")
            unit = known[venue.quotation_unit]
            if venue.quotes_in_subunit and unit.quotation_subunit_of != venue.trading_currency:
                raise ValueError(
                    f"exchange {venue.mic} quotes in {unit.code} but trades in "
                    f"{venue.trading_currency}, and {unit.code} is not a quotation subunit of it"
                )
        return self

    @property
    def mics(self) -> tuple[str, ...]:
        return tuple(e.mic for e in self.exchanges)

    @property
    def currency_codes(self) -> tuple[str, ...]:
        return tuple(c.code for c in self.currencies)

    def exchange(self, mic: str) -> Exchange:
        """The exchange with this MIC, or ``UnknownExchangeError`` — never a guess."""
        for exchange in self.exchanges:
            if exchange.mic == mic:
                return exchange
        raise UnknownExchangeError(mic, self.mics)

    def currency(self, code: str) -> Currency:
        """The currency or quotation unit with this code, or ``UnknownCurrencyError``."""
        for currency in self.currencies:
            if currency.code == code:
                return currency
        raise UnknownCurrencyError(code, self.currency_codes)

    def major_currency_of(self, unit: str) -> Currency:
        """The currency ``unit`` is money in: GBX → GBP, GBP → GBP."""
        currency = self.currency(unit)
        major = currency.quotation_subunit_of
        return currency if major is None else self.currency(major)

    def same_money(self, left: str, right: str) -> bool:
        """True when the two units are the same currency, possibly in different units."""
        return self.major_currency_of(left).code == self.major_currency_of(right).code

    def to_major_currency(self, amount: Decimal, unit: str) -> Decimal:
        """``amount`` expressed in ``unit``'s major currency, exactly.

        ``to_major_currency(Decimal("1234.5"), "GBX") == Decimal("12.345")`` — the third
        decimal is a real half-penny from the original quote and is never rounded away.
        A major currency converts to itself unchanged.
        """
        currency = self.currency(unit)
        return _shift_point(amount, -currency.decimal_places_to_major)

    def from_major_currency(self, amount: Decimal, unit: str) -> Decimal:
        """``amount``, given in ``unit``'s major currency, expressed in ``unit``. Exact inverse."""
        currency = self.currency(unit)
        return _shift_point(amount, currency.decimal_places_to_major)

    def convert(self, amount: Decimal, from_unit: str, to_unit: str) -> Decimal:
        """Scale ``amount`` between two units of the same currency.

        Raises ``UnrelatedCurrencyError`` for genuinely different currencies: an FX rate is
        dated data, not a property of the unit, so it cannot be sourced here.
        """
        source, target = self.currency(from_unit), self.currency(to_unit)
        if source.code == target.code:
            return amount
        if not self.same_money(source.code, target.code):
            raise UnrelatedCurrencyError(source.code, target.code)
        return _shift_point(amount, target.decimal_places_to_major - source.decimal_places_to_major)


class Money(FrozenModel):
    """An amount and the unit it is quoted in — pence and pounds are different units.

    Arithmetic across units raises rather than picking one; ``converted_to`` is the only way
    the unit changes. Division across units raises for the same reason, which is what stops
    a GBX price and a GBP dividend meeting inside a yield calculation.
    """

    amount: Decimal
    unit: str = Field(pattern=r"^[A-Z]{3}$", description="currency or quotation unit, e.g. GBX")

    @field_validator("amount", mode="before")
    @classmethod
    def _no_float_amounts(cls, value: object) -> object:
        if isinstance(value, float):
            raise ValueError(
                "float amounts are not accepted (DEC-005): pass Decimal(str(value)) so the "
                "value you meant is the value stored"
            )
        return value

    @field_validator("amount")
    @classmethod
    def _amount_is_finite(cls, value: Decimal) -> Decimal:
        _decimal_exponent(value)  # raises for NaN/Infinity
        return value

    def converted_to(self, unit: str, *, data: "ReferenceData | None" = None) -> "Money":
        """This amount in ``unit``, exactly, or a typed error. The explicit conversion."""
        reference = data if data is not None else default_reference_data()
        return Money(amount=reference.convert(self.amount, self.unit, unit), unit=unit)

    def _require_same_unit(self, other: "Money", operation: str) -> None:
        if self.unit != other.unit:
            raise CurrencyMismatchError(self.unit, other.unit, operation)

    def __add__(self, other: "Money") -> "Money":
        self._require_same_unit(other, "add")
        return Money(amount=self.amount + other.amount, unit=self.unit)

    def __sub__(self, other: "Money") -> "Money":
        self._require_same_unit(other, "subtract")
        return Money(amount=self.amount - other.amount, unit=self.unit)

    def __truediv__(self, other: "Money") -> Decimal:
        """A dimensionless ratio (yield, payout) — only ever between matching units."""
        self._require_same_unit(other, "divide")
        return self.amount / other.amount


@runtime_checkable
class FxRateProvider(Protocol):
    """A source of dated FX rates. Defined now, implemented when provider data arrives.

    Direction, pinned so an inverted rate cannot become the same class of silent error as
    the pence bug: ``rate(base, quote, on)`` returns **units of ``quote`` per one unit of
    ``base``** on ``on``. ``rate("GBP", "USD", d) == Decimal("1.25")`` means one pound buys
    1.25 dollars, so an amount in GBP is **multiplied** by the rate to become USD.

    ``on`` is the date the rate applied, making implementations point-in-time correct by
    construction: a backtest asks for the rate as it was, never today's. Implementations
    must raise ``FxRateUnavailableError`` for a pair or date they cannot serve — never
    return 1, an inverse computed by division, or a nearest-date substitute.

    Rates are for major currencies (GBP, USD), not quotation subunits; convert a subunit to
    its major currency first. ``convert_with_fx`` does both halves in the right order.
    """

    def rate(self, base: str, quote: str, on: date) -> Decimal: ...


def convert_with_fx(
    money: Money,
    to_unit: str,
    *,
    on: date,
    provider: FxRateProvider,
    data: ReferenceData | None = None,
) -> Money:
    """Convert across currencies: exact unit scaling either side of one dated FX rate.

    GBX → USD is pence → pounds (exact shift), pounds → dollars (multiply by
    ``rate("GBP", "USD", on)``), dollars → target unit (exact shift). Same-currency
    conversions never touch the provider.
    """
    reference = data if data is not None else default_reference_data()
    source_major = reference.major_currency_of(money.unit)
    target_major = reference.major_currency_of(to_unit)
    if source_major.code == target_major.code:
        return money.converted_to(to_unit, data=reference)
    in_major = reference.to_major_currency(money.amount, money.unit)
    rate = provider.rate(source_major.code, target_major.code, on)
    converted = in_major * rate
    return Money(amount=reference.from_major_currency(converted, to_unit), unit=to_unit)


def load_reference_data(path: Path | None = None) -> ReferenceData:
    """Load and fully validate reference data — the packaged file, or an override path."""
    if path is None:
        resource = files("trp.domain") / _REFERENCE_DATA_DIR / _REFERENCE_DATA_FILE
        payload = resource.read_text("utf-8")
    else:
        payload = path.read_text("utf-8")
    return ReferenceData.model_validate_json(payload)


@cache
def default_reference_data() -> ReferenceData:
    """The packaged reference data, parsed once.

    Cached deliberately: this is versioned repository content, not a live lookup, so within
    a process it cannot change underfoot. Pass an explicit ``ReferenceData`` to work against
    anything else.
    """
    return load_reference_data()


def to_major_currency(amount: Decimal, unit: str, *, data: ReferenceData | None = None) -> Decimal:
    """``amount`` in ``unit``'s major currency: 1234.5 GBX → exactly Decimal("12.345") GBP."""
    reference = data if data is not None else default_reference_data()
    return reference.to_major_currency(amount, unit)


def from_major_currency(
    amount: Decimal, unit: str, *, data: ReferenceData | None = None
) -> Decimal:
    """The exact inverse of ``to_major_currency``: 12.345 GBP → Decimal("1234.5") GBX."""
    reference = data if data is not None else default_reference_data()
    return reference.from_major_currency(amount, unit)


def exchange(mic: str, *, data: ReferenceData | None = None) -> Exchange:
    """Look up an exchange by MIC in the default reference data."""
    reference = data if data is not None else default_reference_data()
    return reference.exchange(mic)
