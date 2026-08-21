"""Dated FX rates (QNT-046): converting statement currencies at rates knowable on the day.

Value factors divide a fundamental (GBP, USD or EUR as filed) by a market value in GBP;
QNT-023 deliberately refuses cross-currency conversion inside the fundamentals layer
because an FX rate is dated data, not a property of a unit. This module supplies the
dated data: daily GBPUSD and GBPEUR from EODHD, raw-first into
``data/canonical/fx/``, and a point-in-time converter that only ever looks at rates ON
OR BEFORE the conversion date.

Convention: pairs are quoted as units of foreign currency per 1 GBP, so converting a
foreign amount to GBP DIVIDES by the rate.
"""

import json
import logging
from bisect import bisect_right
from datetime import UTC, date, datetime
from pathlib import Path

import polars as pl

logger = logging.getLogger(__name__)

PAIRS = {"USD": "GBPUSD.FOREX", "EUR": "GBPEUR.FOREX"}

RATE_BANDS = {"USD": (0.8, 3.0), "EUR": (0.8, 3.0)}
"""Sanity bands per pair: a value outside means the series is not what we think."""

MAX_STALENESS_DAYS = 7
"""A conversion refuses rather than reach further back than a week for a rate."""


class FxError(Exception):
    pass


def ingest_fx() -> Path:
    from trp.config import load_settings
    from trp.ingestion.raw import RawStore
    from trp.providers.adapters.eodhd import EodhdProvider
    from trp.providers.base import Dataset

    settings = load_settings()
    store = RawStore(settings.raw_dir)
    provider = EodhdProvider()
    ingested_at = datetime.now(UTC)
    directory = settings.canonical_dir / "fx"
    directory.mkdir(parents=True, exist_ok=True)
    for currency, symbol in PAIRS.items():
        low, high = RATE_BANDS[currency]
        rows: list[dict[str, object]] = []
        for page in provider.prices(symbol, date(1985, 1, 1), ingested_at.date()):
            store.write("eodhd", provider.version, Dataset.PRICES, page)
            for record in json.loads(page.content):
                rate = float(record["close"])
                if not (low <= rate <= high):
                    raise FxError(f"{symbol} {record['date']}: rate {rate} outside sanity band")
                rows.append({"date": date.fromisoformat(record["date"]), "rate": rate})
        frame = pl.DataFrame(rows, schema={"date": pl.Date, "rate": pl.Float64}).sort("date")
        frame.write_parquet(directory / f"gbp{currency.lower()}.parquet")
        logger.info("fx %s: %d rows", currency, frame.height)
    (directory / "provenance.json").write_text(
        json.dumps(
            {
                "pairs": PAIRS,
                "convention": "foreign units per 1 GBP; to-GBP conversion divides",
                "ingested_at": ingested_at.isoformat(),
            },
            indent=2,
        )
    )
    return directory


class FxRates:
    """Point-in-time converter over the canonical FX dataset."""

    def __init__(self, root: Path) -> None:
        self._series: dict[str, tuple[list[date], list[float]]] = {}
        for currency in PAIRS:
            frame = pl.read_parquet(root / f"gbp{currency.lower()}.parquet").sort("date")
            self._series[currency] = (frame["date"].to_list(), frame["rate"].to_list())

    def to_gbp(self, amount: float, currency: str, on: date) -> float:
        """``amount`` of ``currency`` in GBP, at the last rate on or before ``on``.

        GBP passes through; an unknown currency or a stale/absent rate raises — a value
        factor computed at a made-up exchange rate is worse than no value at all."""
        if currency == "GBP":
            return amount
        series = self._series.get(currency)
        if series is None:
            raise FxError(f"no FX series for {currency}; known: GBP, {sorted(self._series)}")
        dates, rates = series
        index = bisect_right(dates, on)
        if index == 0:
            raise FxError(f"no {currency} rate on or before {on}")
        rate_date = dates[index - 1]
        if (on - rate_date).days > MAX_STALENESS_DAYS:
            raise FxError(
                f"latest {currency} rate is {rate_date}, {(on - rate_date).days} days "
                f"before {on} — refusing a stale conversion"
            )
        return amount / rates[index - 1]


if __name__ == "__main__":
    from trp.logging import setup_logging

    setup_logging()
    ingest_fx()
