from datetime import UTC, date, datetime
from decimal import Decimal
from pathlib import Path

import polars as pl
import pytest

from tests.fakes.fx import FixedRateFx
from tests.fixtures.currencies import (
    EUR_GBP,
    FY2019,
    GBP_USD,
    USD_GBP,
    MixedCurrencyUniverse,
    mixed_currency_fx,
    mixed_currency_universe,
    reference_with_eur,
)
from trp.canonical.fundamentals.currency import (
    CONVERSION_CONVENTION,
    MissingColumnsError,
    MixedCurrencyError,
    convert_fundamentals,
    fx_available_at,
    require_single_currency,
    total,
)
from trp.canonical.fundamentals.queries import fundamentals
from trp.canonical.fundamentals.storage import read_fundamentals, write_fundamentals
from trp.domain.fundamentals import FundamentalValue, PeriodType, StatementType
from trp.domain.identifiers import new_security_id
from trp.domain.reference import FxRateUnavailableError, Money

AS_OF = datetime(2026, 1, 1, tzinfo=UTC)
ALL_ITEMS = [
    "revenue",
    "total_equity",
    "capital_expenditure",
    "eps_basic",
    "shares_outstanding",
]


@pytest.fixture
def universe(tmp_path: Path) -> tuple[Path, MixedCurrencyUniverse]:
    scenario = mixed_currency_universe()
    write_fundamentals(list(scenario.records), tmp_path, source="fixture:mixed-currency")
    return tmp_path, scenario


def query(root: Path, scenario: MixedCurrencyUniverse, **kwargs: object) -> pl.DataFrame:
    return fundamentals(root, scenario.security_ids, ALL_ITEMS, as_of=AS_OF, **kwargs)  # type: ignore[arg-type]


def converted(
    root: Path, scenario: MixedCurrencyUniverse, to_currency: str = "GBP"
) -> pl.DataFrame:
    return convert_fundamentals(
        query(root, scenario),
        to_currency=to_currency,
        fx=mixed_currency_fx(),
        as_of=AS_OF,
        fx_source="fixture:mixed-currency-fx",
        reference=reference_with_eur(),
    )


def row_for(
    frame: pl.DataFrame, security_id: str, line_item: str, **extra: object
) -> dict[str, object]:
    subset = frame.filter(
        (pl.col("security_id") == security_id) & (pl.col("line_item") == line_item)
    )
    for column, value in extra.items():
        subset = subset.filter(pl.col(column) == value)
    assert subset.height == 1, f"expected one {line_item} row, got {subset.height}"
    return subset.to_dicts()[0]


def test_a_usd_reporting_uk_company_is_stored_in_usd(
    universe: tuple[Path, MixedCurrencyUniverse],
) -> None:
    """The reported currency survives ingestion: nothing converts on the way in."""
    root, scenario = universe
    stored = read_fundamentals(root, security_ids=[scenario.shell])
    assert set(stored.get_column("currency").to_list()) == {"USD"}
    assert "converted_value" not in stored.columns


def test_conversion_never_touches_the_store(universe: tuple[Path, MixedCurrencyUniverse]) -> None:
    root, scenario = universe
    before = {p: p.read_bytes() for p in sorted(root.rglob("*")) if p.is_file()}
    converted(root, scenario)
    after = {p: p.read_bytes() for p in sorted(root.rglob("*")) if p.is_file()}
    assert before == after  # convert_fundamentals is a read-side view, byte for byte


def test_converted_rows_show_the_original_and_the_conversion(
    universe: tuple[Path, MixedCurrencyUniverse],
) -> None:
    root, scenario = universe
    frame = converted(root, scenario)
    revenue = row_for(frame, scenario.shell, "revenue")

    assert revenue["currency"] == "USD"  # as filed, still here
    assert revenue["value"] == Decimal("300000000000")
    assert revenue["converted_value"] == Decimal("240000000000")  # 300bn USD at 0.8
    assert revenue["target_currency"] == "GBP"
    assert Decimal(str(revenue["fx_rate"])) == USD_GBP  # exact string, round-trips
    assert revenue["fx_rate_date"] == FY2019  # the convention: period-end spot
    assert revenue["fx_rate_available_at"] == fx_available_at(FY2019)
    assert revenue["fx_source"] == "fixture:mixed-currency-fx"
    assert revenue["converted"] is True
    assert revenue["conversion_note"] is None
    assert CONVERSION_CONVENTION == "period-end spot"


def test_every_reporting_currency_in_the_universe_converts_consistently(
    universe: tuple[Path, MixedCurrencyUniverse],
) -> None:
    root, scenario = universe
    frame = converted(root, scenario)

    assert row_for(frame, scenario.shell, "total_equity")["converted_value"] == Decimal(
        "144000000000"
    )
    assert row_for(frame, scenario.shell, "capital_expenditure")["converted_value"] == Decimal(
        "-17600000000"
    )  # an outflow stays an outflow
    assert (
        row_for(frame, scenario.eur_reporter, "revenue", period_end=FY2019)["converted_value"]
        == Decimal("90000000000") * EUR_GBP
    )

    # The GBP reporter needs no rate at all, and must not be charged one.
    gbp_revenue = row_for(frame, scenario.gbp_reporter, "revenue")
    assert gbp_revenue["converted_value"] == Decimal("60000000000")
    assert gbp_revenue["fx_rate"] is None
    assert gbp_revenue["converted"] is True

    # Converted, the whole FY2019 universe is finally addable.
    money = total(
        frame.filter((pl.col("line_item") == "revenue") & (pl.col("period_end") == FY2019)),
        value_column="converted_value",
        currency_column="target_currency",
    )
    assert money == Money(
        amount=Decimal("240000000000") + Decimal("60000000000") + Decimal("76500000000"),
        unit="GBP",
    )


def test_pence_and_pounds_convert_exactly_and_without_an_fx_rate(
    universe: tuple[Path, MixedCurrencyUniverse],
) -> None:
    """EPS in pence against a sterling base is a decimal shift, not an FX conversion."""
    root, scenario = universe
    eps = row_for(converted(root, scenario), scenario.gbp_reporter, "eps_basic")
    assert eps["currency"] == "GBX"
    assert eps["value"] == Decimal("42.5")
    assert eps["converted_value"] == Decimal("0.425")  # exactly, no rounding step
    assert eps["fx_rate"] is None


def test_pence_crossing_a_currency_boundary_goes_through_the_major_currency(
    universe: tuple[Path, MixedCurrencyUniverse],
) -> None:
    root, scenario = universe
    eps = row_for(converted(root, scenario, to_currency="USD"), scenario.gbp_reporter, "eps_basic")
    assert eps["converted_value"] == Decimal("0.425") * GBP_USD  # 42.5p → £0.425 → $0.53125
    assert Decimal(str(eps["fx_rate"])) == GBP_USD


def test_a_share_count_is_never_multiplied_by_an_exchange_rate(
    universe: tuple[Path, MixedCurrencyUniverse],
) -> None:
    root, scenario = universe
    shares = row_for(
        converted(root, scenario, to_currency="USD"), scenario.gbp_reporter, "shares_outstanding"
    )
    assert shares["unit_kind"] == "share_count"
    assert shares["converted"] is False
    assert shares["converted_value"] is None
    assert "not a monetary amount" in str(shares["conversion_note"])
    assert shares["value"] == Decimal("2000000000")  # the count itself is untouched


def test_a_missing_rate_raises_rather_than_passing_the_number_through(
    universe: tuple[Path, MixedCurrencyUniverse],
) -> None:
    root, scenario = universe
    without_eur = FixedRateFx({("USD", "GBP"): USD_GBP})
    with pytest.raises(FxRateUnavailableError, match="EUR/GBP"):
        convert_fundamentals(
            query(root, scenario),
            to_currency="GBP",
            fx=without_eur,
            as_of=AS_OF,
            reference=reference_with_eur(),
        )


def test_a_missing_rate_may_be_flagged_but_never_silently_skipped(
    universe: tuple[Path, MixedCurrencyUniverse],
) -> None:
    root, scenario = universe
    frame = convert_fundamentals(
        query(root, scenario),
        to_currency="GBP",
        fx=FixedRateFx({("USD", "GBP"): USD_GBP}),
        as_of=AS_OF,
        strict=False,
        reference=reference_with_eur(),
    )
    eur_revenue = row_for(frame, scenario.eur_reporter, "revenue", period_end=FY2019)
    assert eur_revenue["converted"] is False
    assert eur_revenue["converted_value"] is None  # not the unconverted number
    assert "no EUR/GBP rate" in str(eur_revenue["conversion_note"])
    assert eur_revenue["value"] == Decimal("90000000000")  # still legible, still in euro
    assert eur_revenue["fx_source"] is None
    # The rows that could be converted still were.
    assert row_for(frame, scenario.shell, "revenue")["converted"] is True


def test_a_reporting_currency_change_between_periods_is_handled_period_by_period(
    universe: tuple[Path, MixedCurrencyUniverse],
) -> None:
    """Not a revision (QNT-022's key excludes currency): each period keeps its own."""
    root, scenario = universe
    frame = converted(root, scenario)
    euro_period = row_for(frame, scenario.eur_reporter, "revenue", period_end=FY2019)
    dollar_period = row_for(frame, scenario.eur_reporter, "revenue", period_end=date(2020, 12, 31))

    assert (euro_period["currency"], dollar_period["currency"]) == ("EUR", "USD")
    assert euro_period["converted_value"] == Decimal("76500000000")
    assert dollar_period["converted_value"] == Decimal("84000000000")
    assert euro_period["fx_rate_date"] == FY2019
    assert dollar_period["fx_rate_date"] == date(2020, 12, 31)  # each period's own rate date


def test_unconverted_mixed_currency_rows_refuse_to_combine(
    universe: tuple[Path, MixedCurrencyUniverse],
) -> None:
    root, scenario = universe
    frame = query(root, scenario).filter(pl.col("line_item") == "revenue")
    with pytest.raises(MixedCurrencyError, match="EUR"):
        total(frame)
    with pytest.raises(MixedCurrencyError):
        require_single_currency(frame)

    single = frame.filter(pl.col("security_id") == scenario.gbp_reporter)
    assert require_single_currency(single) == "GBP"
    assert total(single) == Money(amount=Decimal("60000000000"), unit="GBP")


def test_rounding_is_explicit_and_documented(tmp_path: Path) -> None:
    """Six decimal places, banker's rounding, applied once after the multiplication."""
    security_id = new_security_id()
    write_fundamentals(
        [
            FundamentalValue(
                security_id=security_id,
                statement=StatementType.INCOME,
                line_item="eps_basic",
                period_end=FY2019,
                period_type=PeriodType.ANNUAL,
                currency="USD",
                value=Decimal("1"),
                available_at=datetime(2020, 3, 1, tzinfo=UTC),
                source="fixture:rounding",
            )
        ],
        tmp_path,
        source="fixture:rounding",
    )
    frame = convert_fundamentals(
        fundamentals(tmp_path, [security_id], ["eps_basic"], as_of=AS_OF),
        to_currency="GBP",
        fx=FixedRateFx({("USD", "GBP"): Decimal("1.234567891")}),
        as_of=AS_OF,
    )
    row = frame.to_dicts()[0]
    assert row["converted_value"] == Decimal("1.234568")  # 1.2345678|91 → half-even at 6dp
    assert row["fx_rate"] == "1.234567891"  # the rate itself is recorded unrounded


def test_the_frame_must_be_a_fundamentals_result_and_as_of_must_be_aware(
    universe: tuple[Path, MixedCurrencyUniverse],
) -> None:
    root, scenario = universe
    with pytest.raises(MissingColumnsError, match="currency"):
        convert_fundamentals(
            pl.DataFrame({"security_id": ["x"]}),
            to_currency="GBP",
            fx=mixed_currency_fx(),
            as_of=AS_OF,
        )
    with pytest.raises(ValueError, match="timezone-aware"):
        convert_fundamentals(
            query(root, scenario),
            to_currency="GBP",
            fx=mixed_currency_fx(),
            as_of=datetime(2020, 1, 1),  # noqa: DTZ001
            reference=reference_with_eur(),
        )


def test_an_empty_result_converts_to_an_empty_frame_with_the_conversion_columns(
    universe: tuple[Path, MixedCurrencyUniverse],
) -> None:
    root, scenario = universe
    empty = fundamentals(
        root, scenario.security_ids, ALL_ITEMS, as_of=datetime(2000, 1, 1, tzinfo=UTC)
    )
    assert empty.is_empty()
    frame = convert_fundamentals(
        empty,
        to_currency="GBP",
        fx=mixed_currency_fx(),
        as_of=AS_OF,
        reference=reference_with_eur(),
    )
    assert frame.is_empty()
    assert {"converted_value", "fx_rate", "fx_rate_available_at", "converted"} <= set(frame.columns)
