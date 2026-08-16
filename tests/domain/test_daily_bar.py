from datetime import UTC, date, datetime
from decimal import Decimal
from pathlib import Path

import polars as pl
import pytest
from pydantic import ValidationError

from trp.canonical.prices import PRICES_DAILY_SCHEMA, bars_to_frame, frame_to_bars
from trp.domain.identifiers import new_security_id
from trp.domain.prices import DailyBar

INGESTED = datetime(2026, 8, 16, 6, 0, tzinfo=UTC)


def bar(**overrides: object) -> DailyBar:
    fields: dict[str, object] = {
        "security_id": new_security_id(),
        "trade_date": date(2020, 3, 2),
        "open": Decimal("101.5"),
        "high": Decimal("103.25"),
        "low": Decimal("100.0"),
        "close": Decimal("102.75"),
        "volume": 1_500_000,
        "currency": "GBX",
        "source": "test",
        "ingested_at": INGESTED,
    }
    fields.update(overrides)
    return DailyBar(**fields)  # type: ignore[arg-type]


def test_valid_bar_constructs_and_preserves_decimals() -> None:
    b = bar()
    assert b.close == Decimal("102.75")
    assert b.currency == "GBX"  # quotation unit recorded, never converted


def test_degenerate_flat_bar_is_valid() -> None:
    price = Decimal("47")
    b = bar(open=price, high=price, low=price, close=price, volume=0)
    assert b.open == b.high == b.low == b.close


@pytest.mark.parametrize(
    ("overrides", "invariant"),
    [
        ({"high": Decimal("99")}, "high >= low"),
        ({"high": Decimal("101"), "open": Decimal("101.5"), "low": Decimal("100")}, "high >= open"),
        ({"close": Decimal("104")}, "high >= close"),
        ({"low": Decimal("102"), "open": Decimal("101.5")}, "low <= open"),
        (
            {"low": Decimal("103"), "open": Decimal("103"), "close": Decimal("102.75")},
            "low <= close",
        ),
    ],
)
def test_impossible_bars_rejected_naming_the_invariant(
    overrides: dict[str, object], invariant: str
) -> None:
    with pytest.raises(ValidationError, match=invariant.replace(">=", ">=")):
        bar(**overrides)


def test_zero_and_negative_prices_rejected() -> None:
    with pytest.raises(ValidationError):
        bar(open=Decimal("0"), low=Decimal("0"))
    with pytest.raises(ValidationError):
        bar(close=Decimal("-1"), low=Decimal("-1"))


def test_fractional_volume_rejected_not_rounded() -> None:
    with pytest.raises(ValidationError):
        bar(volume=1500.5)


def test_bars_are_immutable() -> None:
    b = bar()
    with pytest.raises(ValidationError):
        b.close = Decimal("999")  # type: ignore[misc]


def test_naive_ingested_at_rejected() -> None:
    with pytest.raises(ValidationError, match="timezone-aware"):
        bar(ingested_at=datetime(2026, 8, 16, 6, 0))  # noqa: DTZ001 — the point of the test


def test_declared_parquet_schema_is_pinned(tmp_path: Path) -> None:
    frame = bars_to_frame([bar(), bar(trade_date=date(2020, 3, 3))])
    path = tmp_path / "prices.parquet"
    frame.write_parquet(path)
    on_disk = pl.read_parquet(path)
    assert dict(on_disk.schema) == dict(pl.Schema(PRICES_DAILY_SCHEMA))
    # Decimal round trip is exact, not float-approximate.
    assert frame_to_bars(on_disk)[0].close == Decimal("102.75")


def test_provider_adjusted_close_is_cross_check_only() -> None:
    b = bar(provider_adjusted_close=Decimal("51.375"))
    # The as-traded close is untouched by the provider's adjusted value.
    assert b.close == Decimal("102.75")
    assert b.provider_adjusted_close == Decimal("51.375")
