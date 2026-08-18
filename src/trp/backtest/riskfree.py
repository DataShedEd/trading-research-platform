"""UK risk-free series (QNT-096): the 3-month gilt yield, so Sharpe stops assuming zero.

EODHD's ``UK3M.GBOND`` gives the annualised 3-month gilt yield daily from December 2009 —
covering the DEC-014 research window. Ingestion is raw-first like everything else; the
canonical copy lives under ``data/canonical/riskfree/``.

The runner passes each run's WINDOW-MEAN annual rate into the metrics as the risk-free
rate, with the source string recording exactly that. A window-mean constant is a
documented approximation: fine for full-sample Sharpe over a rate regime, understating
the dispersion a per-period excess-return treatment would show — that refinement belongs
with regime-focused work, not here.
"""

import json
import logging
from datetime import UTC, date, datetime
from pathlib import Path

import polars as pl

logger = logging.getLogger(__name__)

SERIES_NAME = "uk3m-gbond"
SYMBOL = "UK3M.GBOND"

RATE_FLOOR = -0.02
RATE_CEILING = 0.20
"""Annual-rate sanity band: a value outside it means the series is not what we think."""


class RiskFreeError(Exception):
    pass


def ingest_risk_free() -> Path:
    """Fetch the gilt-yield series through the raw store and canonicalise it."""
    from trp.config import load_settings
    from trp.ingestion.raw import RawStore
    from trp.providers.adapters.eodhd import EodhdProvider
    from trp.providers.base import Dataset

    settings = load_settings()
    store = RawStore(settings.raw_dir)
    provider = EodhdProvider()
    ingested_at = datetime.now(UTC)
    rows: list[dict[str, object]] = []
    for page in provider.prices(SYMBOL, date(2009, 1, 1), ingested_at.date()):
        store.write("eodhd", provider.version, Dataset.PRICES, page)
        for record in json.loads(page.content):
            rate = float(record["close"]) / 100  # served in percent
            if not (RATE_FLOOR <= rate <= RATE_CEILING):
                raise RiskFreeError(
                    f"{record['date']}: {record['close']} is outside the annual-rate "
                    f"sanity band — {SYMBOL} is not serving what we think it is"
                )
            rows.append({"date": date.fromisoformat(record["date"]), "annual_rate": rate})
    frame = pl.DataFrame(rows, schema={"date": pl.Date, "annual_rate": pl.Float64}).sort("date")
    directory = settings.canonical_dir / "riskfree" / SERIES_NAME
    directory.mkdir(parents=True, exist_ok=True)
    frame.write_parquet(directory / "series.parquet")
    (directory / "provenance.json").write_text(
        json.dumps(
            {
                "symbol": SYMBOL,
                "description": "UK 3-month gilt yield, annualised, decimal",
                "ingested_at": ingested_at.isoformat(),
                "rows": frame.height,
            },
            indent=2,
        )
    )
    logger.info("risk-free series: %d rows to %s", frame.height, directory)
    return directory


def load_risk_free(root: Path) -> pl.DataFrame:
    frame = pl.read_parquet(root / SERIES_NAME / "series.parquet")
    bad = frame.filter(
        (pl.col("annual_rate") < RATE_FLOOR) | (pl.col("annual_rate") > RATE_CEILING)
    )
    if bad.height:
        raise RiskFreeError(f"{bad.height} rows outside the annual-rate sanity band")
    return frame


def window_mean_rate(series: pl.DataFrame, start: date, end: date) -> tuple[float, str]:
    """The mean annual rate over [start, end] plus the source string metrics record."""
    window = series.filter((pl.col("date") >= start) & (pl.col("date") <= end))
    if window.height == 0:
        raise RiskFreeError(f"risk-free series has no observations in {start}..{end}")
    mean = window["annual_rate"].mean()
    assert isinstance(mean, float)
    source = (
        f"mean UK 3-month gilt yield {start}..{end} ({SYMBOL}, EODHD), "
        f"{window.height} observations; window-mean constant is a documented approximation"
    )
    return mean, source


if __name__ == "__main__":
    from trp.logging import setup_logging

    setup_logging()
    ingest_risk_free()
