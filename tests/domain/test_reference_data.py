"""Exchange/currency reference data and the GBX/GBP policy (QNT-017).

The bug under test throughout: a price quoted in pence meeting a dividend declared in
pounds inside a factor computation, producing a number wrong by exactly one hundred that
still looks like a number. Conversion assertions are exact on Decimal digits *and*
exponent, never approximate — a rounding step in unit conversion would itself be a defect.
"""

import json
from collections.abc import Callable
from datetime import date
from decimal import Decimal, localcontext
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

import pytest
from pydantic import ValidationError

from tests.fakes.fx import FixedRateFx
from trp.domain.reference import (
    CurrencyMismatchError,
    Exchange,
    FxRateProvider,
    FxRateUnavailableError,
    Money,
    ReferenceData,
    UnknownCurrencyError,
    UnknownExchangeError,
    UnrelatedCurrencyError,
    convert_with_fx,
    default_reference_data,
    exchange,
    from_major_currency,
    load_reference_data,
    to_major_currency,
)

ON = date(2020, 3, 2)

GBP_RECORD: dict[str, object] = {"code": "GBP", "name": "Pound sterling", "minor_unit": 2}
GBX_RECORD: dict[str, object] = {
    "code": "GBX",
    "name": "Penny sterling",
    "minor_unit": 0,
    "quotation_subunit_of": "GBP",
    "units_per_major": 100,
}
USD_RECORD: dict[str, object] = {"code": "USD", "name": "United States dollar", "minor_unit": 2}
LSE_RECORD: dict[str, object] = {
    "mic": "XLON",
    "name": "London Stock Exchange",
    "country": "GB",
    "timezone": "Europe/London",
    "trading_currency": "GBP",
    "quotation_unit": "GBX",
}
VALID_FILE: dict[str, object] = {
    "currencies": [GBP_RECORD, GBX_RECORD],
    "exchanges": [LSE_RECORD],
}


@pytest.fixture
def data() -> ReferenceData:
    return default_reference_data()


class Exactly:
    """Equal only to a Decimal with the same digits *and* exponent.

    ``Decimal("12.345") == Decimal("12.3450")`` is true, but a conversion that moved the
    exponent has scaled or rounded something, and that is what these tests are about.
    """

    def __init__(self, value: str) -> None:
        self.value = Decimal(value)

    def __eq__(self, other: object) -> bool:
        return isinstance(other, Decimal) and other.as_tuple() == self.value.as_tuple()

    def __hash__(self) -> int:
        return hash(self.value)

    def __repr__(self) -> str:
        return f"exactly {self.value}"


def write_reference(tmp_path: Path, payload: dict[str, object], name: str) -> Path:
    path = tmp_path / f"{name}.json"
    path.write_text(json.dumps(payload), encoding="utf-8")
    return path


# --- the committed reference file ------------------------------------------------------


def test_packaged_file_defines_the_three_required_exchanges(data: ReferenceData) -> None:
    assert set(data.mics) >= {"XLON", "XNYS", "XNAS"}
    for mic in ("XLON", "XNYS", "XNAS"):
        record = data.exchange(mic)
        assert record.name and record.country and record.trading_currency
        # The timezone is a real zone, not a plausible-looking string.
        assert ZoneInfo(record.timezone).key == record.timezone


def test_exchange_records_carry_the_quotation_unit_not_only_the_currency(
    data: ReferenceData,
) -> None:
    lse = data.exchange("XLON")
    assert (lse.trading_currency, lse.quotation_unit) == ("GBP", "GBX")
    assert lse.quotes_in_subunit is True
    for mic in ("XNYS", "XNAS"):
        us = data.exchange(mic)
        assert (us.trading_currency, us.quotation_unit) == ("USD", "USD")
        assert us.quotes_in_subunit is False


def test_exchanges_come_from_the_file_not_from_python(tmp_path: Path) -> None:
    """Loading a different file gives different exchanges: the list is data, not code."""
    assert load_reference_data() == default_reference_data()
    other = load_reference_data(write_reference(tmp_path, VALID_FILE, "one_exchange"))
    assert other.mics == ("XLON",)
    assert other.currency("GBX").units_per_major == 100


def test_gbx_gbp_relationship_is_data_with_a_factor_of_exactly_100(data: ReferenceData) -> None:
    gbx = data.currency("GBX")
    assert gbx.is_quotation_subunit
    assert gbx.quotation_subunit_of == "GBP"
    assert gbx.units_per_major == 100
    assert gbx.decimal_places_to_major == 2
    assert data.major_currency_of("GBX").code == "GBP"
    assert data.major_currency_of("GBP").code == "GBP"  # a major currency is its own major
    assert data.currency("GBP").is_quotation_subunit is False


# --- exact conversion -------------------------------------------------------------------


def test_pence_to_pounds_is_exact_to_the_half_penny(data: ReferenceData) -> None:
    assert to_major_currency(Decimal("1234.5"), "GBX", data=data) == Exactly("12.345")
    assert to_major_currency(Decimal("4521.5"), "GBX", data=data) == Exactly("45.215")


def test_pounds_to_pence_is_the_exact_inverse(data: ReferenceData) -> None:
    assert from_major_currency(Decimal("12.345"), "GBX", data=data) == Exactly("1234.5")


@pytest.mark.parametrize(
    "pence",
    [
        "1234.5",
        "0.5",
        "0.000001",
        "-873.25",
        "0",
        "123456789012345678901234567890.5",  # more digits than the default context precision
    ],
)
def test_round_trip_gbx_gbp_gbx_is_exact(pence: str, data: ReferenceData) -> None:
    pounds = data.to_major_currency(Decimal(pence), "GBX")
    assert data.from_major_currency(pounds, "GBX") == Exactly(pence)


def test_conversion_ignores_decimal_context_precision(data: ReferenceData) -> None:
    """Scaling shifts the exponent; it must not go through division, which would round."""
    long_value = Decimal("123456789012345678901234567890.5")
    with localcontext() as ctx:
        ctx.prec = 5
        converted = data.to_major_currency(long_value, "GBX")
        assert converted == Exactly("1234567890123456789012345678.905")
        assert long_value / Decimal(100) != converted  # what the naive implementation gives


def test_converting_a_major_currency_to_itself_changes_nothing(data: ReferenceData) -> None:
    assert data.to_major_currency(Decimal("45.215"), "GBP") == Exactly("45.215")
    assert data.convert(Decimal("45.215"), "GBP", "GBP") == Exactly("45.215")
    assert data.convert(Decimal("45.215"), "USD", "USD") == Exactly("45.215")


def test_convert_moves_between_related_units_in_both_directions(data: ReferenceData) -> None:
    assert data.convert(Decimal("4521.5"), "GBX", "GBP") == Exactly("45.215")
    assert data.convert(Decimal("45.215"), "GBP", "GBX") == Exactly("4521.5")


# --- refusals ---------------------------------------------------------------------------


@pytest.mark.parametrize(("source", "target"), [("GBX", "USD"), ("GBP", "USD"), ("USD", "GBX")])
def test_unrelated_currencies_raise_and_point_at_the_fx_interface(
    source: str, target: str, data: ReferenceData
) -> None:
    with pytest.raises(UnrelatedCurrencyError, match="FxRateProvider") as excinfo:
        data.convert(Decimal("100"), source, target)
    assert (excinfo.value.from_unit, excinfo.value.to_unit) == (source, target)


def test_unrelated_conversion_does_not_return_the_amount_unchanged(data: ReferenceData) -> None:
    """The failure mode being excluded: a no-op 'conversion' that looks like it worked."""
    with pytest.raises(UnrelatedCurrencyError):
        data.convert(Decimal("45.215"), "GBP", "USD")


def test_unknown_mic_raises_a_typed_error_listing_what_is_known(data: ReferenceData) -> None:
    with pytest.raises(UnknownExchangeError) as excinfo:
        data.exchange("XXXX")
    assert excinfo.value.mic == "XXXX"
    assert "XLON" in str(excinfo.value)
    with pytest.raises(UnknownExchangeError):
        exchange("XSWX")  # not a venue this platform ingests


def test_unknown_currency_raises_a_typed_error(data: ReferenceData) -> None:
    with pytest.raises(UnknownCurrencyError) as excinfo:
        data.currency("ZZZ")
    assert excinfo.value.code == "ZZZ"
    with pytest.raises(UnknownCurrencyError):
        to_major_currency(Decimal("1"), "ZZZ", data=data)


# --- Money: the arithmetic path ---------------------------------------------------------

PRICE_GBX = Money(amount=Decimal("4521.5"), unit="GBX")  # LSE quote, pence
DIVIDEND_GBP = Money(amount=Decimal("45.215"), unit="GBP")  # declared in pounds


@pytest.mark.parametrize(
    ("operation", "apply"),
    [
        ("add", lambda a, b: a + b),
        ("subtract", lambda a, b: a - b),
        ("divide", lambda a, b: b / a),
    ],
)
def test_gbx_price_and_gbp_dividend_cannot_be_combined_without_conversion(
    operation: str, apply: Callable[[Money, Money], Any]
) -> None:
    with pytest.raises(CurrencyMismatchError, match=operation):
        apply(PRICE_GBX, DIVIDEND_GBP)


def test_the_converted_yield_is_exact_and_the_unconverted_one_is_impossible() -> None:
    dividend = Money(amount=Decimal("0.45215"), unit="GBP")
    # Explicit conversion first, then a dimensionless ratio: 0.45215 / 45.215 = 1%.
    assert dividend / PRICE_GBX.converted_to("GBP") == Decimal("0.01")
    # Without it there is no answer at all — rather than one that is a hundredfold wrong.
    with pytest.raises(CurrencyMismatchError):
        dividend / PRICE_GBX


def test_same_unit_arithmetic_is_allowed_and_keeps_the_unit() -> None:
    total = Money(amount=Decimal("100.5"), unit="GBX") + Money(amount=Decimal("0.5"), unit="GBX")
    assert total.unit == "GBX"
    assert total.amount == Decimal("101.0")
    assert (total - Money(amount=Decimal("1"), unit="GBX")).amount == Decimal("100.0")
    assert Money(amount=Decimal("50"), unit="GBX") / Money(amount=Decimal("200"), unit="GBX") == (
        Decimal("0.25")
    )


def test_money_conversion_is_explicit_and_exact() -> None:
    assert PRICE_GBX.converted_to("GBP") == Money(amount=Decimal("45.215"), unit="GBP")
    with pytest.raises(UnrelatedCurrencyError):
        DIVIDEND_GBP.converted_to("USD")


def test_money_rejects_floats_rather_than_coercing_them() -> None:
    with pytest.raises(ValidationError, match="float"):
        Money(amount=0.1 + 0.2, unit="GBP")  # type: ignore[arg-type]


def test_money_rejects_non_finite_amounts_and_lowercase_units() -> None:
    with pytest.raises(ValidationError):
        Money(amount=Decimal("NaN"), unit="GBP")
    with pytest.raises(ValidationError):
        Money(amount=Decimal("1"), unit="gbx")


def test_money_is_immutable() -> None:
    with pytest.raises(ValidationError):
        PRICE_GBX.unit = "GBP"


# --- FX interface -----------------------------------------------------------------------


def test_fixed_rate_fake_satisfies_the_protocol() -> None:
    provider: FxRateProvider = FixedRateFx({("GBP", "USD"): Decimal("1.25")})
    assert isinstance(provider, FxRateProvider)
    assert provider.rate("GBP", "USD", ON) == Decimal("1.25")


def test_rate_direction_is_quote_units_per_base_unit() -> None:
    fx = FixedRateFx({("GBP", "USD"): Decimal("1.25")})
    # One pound buys 1.25 dollars, so pounds MULTIPLIED by the rate give dollars.
    dollars = convert_with_fx(DIVIDEND_GBP, "USD", on=ON, provider=fx)
    assert dollars == Money(amount=Decimal("56.51875"), unit="USD")
    assert dollars.amount > DIVIDEND_GBP.amount  # an inverted rate fails this


def test_fx_conversion_crosses_the_quotation_unit_first() -> None:
    fx = FixedRateFx({("GBP", "USD"): Decimal("1.25")})
    assert convert_with_fx(PRICE_GBX, "USD", on=ON, provider=fx) == Money(
        amount=Decimal("56.51875"), unit="USD"
    )
    # The rate was asked for in major currencies, for the date given — never in pence.
    assert fx.calls == [("GBP", "USD", ON)]


def test_fx_conversion_within_one_currency_never_consults_the_provider() -> None:
    fx = FixedRateFx()
    assert convert_with_fx(PRICE_GBX, "GBP", on=ON, provider=fx) == Money(
        amount=Decimal("45.215"), unit="GBP"
    )
    assert fx.calls == []


def test_missing_rate_raises_rather_than_defaulting_to_one_or_inverting() -> None:
    fx = FixedRateFx({("GBP", "USD"): Decimal("1.25")})
    with pytest.raises(FxRateUnavailableError):
        fx.rate("USD", "GBP", ON)  # scripted one way only; no silent 1/1.25
    with pytest.raises(FxRateUnavailableError):
        convert_with_fx(Money(amount=Decimal("10"), unit="USD"), "GBP", on=ON, provider=fx)


# --- file validation --------------------------------------------------------------------


def test_the_valid_fixture_file_loads(tmp_path: Path) -> None:
    assert load_reference_data(write_reference(tmp_path, VALID_FILE, "valid")).mics == ("XLON",)


@pytest.mark.parametrize(
    ("name", "payload", "message"),
    [
        (
            "unknown_currency",
            {**VALID_FILE, "exchanges": [{**LSE_RECORD, "quotation_unit": "USD"}]},
            "not defined",
        ),
        (
            "duplicate_mic",
            {**VALID_FILE, "exchanges": [LSE_RECORD, LSE_RECORD]},
            "duplicate exchange MICs",
        ),
        (
            "bad_timezone",
            {**VALID_FILE, "exchanges": [{**LSE_RECORD, "timezone": "Europe/Camelot"}]},
            "IANA timezone",
        ),
        (
            "non_power_of_ten_factor",
            {
                **VALID_FILE,
                "currencies": [GBP_RECORD, {**GBX_RECORD, "units_per_major": 240}],
            },
            "power of ten",
        ),
        (
            "subunit_without_factor",
            {
                **VALID_FILE,
                "currencies": [
                    GBP_RECORD,
                    {k: v for k, v in GBX_RECORD.items() if k != "units_per_major"},
                ],
            },
            "must be given together",
        ),
        (
            "quotation_unit_of_another_currency",
            {
                "currencies": [GBP_RECORD, GBX_RECORD, USD_RECORD],
                "exchanges": [{**LSE_RECORD, "trading_currency": "USD"}],
            },
            "not a quotation subunit of it",
        ),
        (
            "duplicate_currency",
            {**VALID_FILE, "currencies": [GBP_RECORD, GBX_RECORD, GBP_RECORD]},
            "duplicate currency codes",
        ),
    ],
)
def test_incoherent_reference_files_are_rejected_at_load(
    name: str, payload: dict[str, object], message: str, tmp_path: Path
) -> None:
    with pytest.raises(ValidationError, match=message):
        load_reference_data(write_reference(tmp_path, payload, name))


def test_exchange_records_are_immutable() -> None:
    record = Exchange(
        mic="XLON",
        name="London Stock Exchange",
        country="GB",
        timezone="Europe/London",
        trading_currency="GBP",
        quotation_unit="GBX",
    )
    with pytest.raises(ValidationError):
        record.quotation_unit = "GBP"
