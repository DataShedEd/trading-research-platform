"""Declared schema and dataframe conversion for the prices_daily table.

The Parquet schema is pinned, never inferred (the QNT-008 pattern): Decimal precision and
scale are chosen to hold both pence-quoted LSE prices and high-priced US securities
exactly. Partitioned storage lands in QNT-018; this module owns the row shape.
"""

import polars as pl

from trp.domain.prices import DailyBar

# 18 digits, 6 decimal places: exact up to ~1e12 in the quotation unit — ample headroom
# for GBX quotes and six-figure USD prices alike.
PRICE_DECIMAL = pl.Decimal(precision=18, scale=6)

PRICES_DAILY_SCHEMA: dict[str, pl.DataType | type[pl.DataType]] = {
    "security_id": pl.Utf8,
    "trade_date": pl.Date,
    "open": PRICE_DECIMAL,
    "high": PRICE_DECIMAL,
    "low": PRICE_DECIMAL,
    "close": PRICE_DECIMAL,
    "volume": pl.Int64,
    "currency": pl.Utf8,
    "source": pl.Utf8,
    "ingested_at": pl.Datetime(time_unit="us", time_zone="UTC"),
    "provider_adjusted_close": PRICE_DECIMAL,
}


def bars_to_frame(bars: list[DailyBar]) -> pl.DataFrame:
    rows = [bar.model_dump(mode="python") for bar in bars]
    frame = pl.DataFrame(rows, schema=PRICES_DAILY_SCHEMA)
    return frame.sort(["security_id", "trade_date"])


def frame_to_bars(frame: pl.DataFrame) -> list[DailyBar]:
    return [DailyBar(**row) for row in frame.iter_rows(named=True)]
