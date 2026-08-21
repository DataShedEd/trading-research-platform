"""Dated shares-outstanding series (QNT-098): the share basis that matches the prices.

EODHD's top-level ``outstandingShares`` series is correct where the balance-sheet field
is not (Shell: 6.21bn vs a bogus 1.62bn) and — crucially — sits on the same share basis
as EODHD's price series even where that basis is a retroactively applied consolidation
(Capita at 15:1, Hammerson at 10:1). Market values built as price x THIS series are
therefore consistent exactly where the individually-inspected inputs look strange.

Availability: an entry dated d is treated as knowable at d + 30 days (share counts are
public via RNS within days of changing; the 30-day lag is the DEC-007 safe direction).
Vendor entries dated in the future (projections) are dropped. The series is
vendor-maintained and may be revisionist — recorded here, measured by the QNT-098
validation harness rather than assumed away.
"""

import json
import logging
from bisect import bisect_right
from datetime import date, timedelta
from pathlib import Path

import polars as pl

logger = logging.getLogger(__name__)

AVAILABILITY_LAG = timedelta(days=30)


class SharesError(Exception):
    pass


def canonicalise_shares() -> Path:
    """Extract every archived fundamentals payload's dated share series."""
    from trp.canonical.fundamentals.ingest_eodhd import _archived_symbols
    from trp.canonical.security_store import read_security_master
    from trp.config import load_settings
    from trp.ingestion.raw import RawStore
    from trp.universe.ftse_build import _eodhd_code_pairs

    settings = load_settings()
    store = RawStore(settings.raw_dir)
    master = read_security_master(settings.canonical_dir / "securities")
    by_symbol = {f"{code.partition('.')[0]}:XLON": sid for sid, code in _eodhd_code_pairs(master)}
    today = _today()
    rows: list[dict[str, object]] = []
    for symbol, meta in sorted(_archived_symbols(store).items()):
        security_id = by_symbol.get(symbol)
        _record, content = store.read(meta)  # type: ignore[arg-type]
        if security_id is None or content is None:
            continue
        doc = json.loads(content)
        for section in ("annual", "quarterly"):
            for entry in doc.get("outstandingShares", {}).get(section, {}).values():
                raw_date = entry.get("dateFormatted")
                shares = entry.get("shares")
                if not raw_date or not shares:
                    continue
                try:
                    on = date.fromisoformat(str(raw_date))
                except ValueError:
                    continue
                if on > today or float(shares) <= 0:
                    continue  # vendor projections and junk are not facts
                rows.append(
                    {
                        "security_id": security_id,
                        "date": on,
                        "shares": float(shares),
                        "available_from": on + AVAILABILITY_LAG,
                    }
                )
    frame = (
        pl.DataFrame(
            rows,
            schema={
                "security_id": pl.Utf8,
                "date": pl.Date,
                "shares": pl.Float64,
                "available_from": pl.Date,
            },
        )
        .unique(subset=["security_id", "date"], keep="last")
        .sort(["security_id", "date"])
    )
    frame, corrections = _continuity_guard(frame)
    logger.info("continuity guard corrected %d entries", corrections)
    directory = settings.canonical_dir / "shares"
    directory.mkdir(parents=True, exist_ok=True)
    frame.write_parquet(directory / "outstanding.parquet")
    securities = frame["security_id"].n_unique()
    logger.info("shares series: %d rows, %d securities", frame.height, securities)
    return directory


def _continuity_guard(frame: pl.DataFrame) -> tuple[pl.DataFrame, int]:
    """Vendor glitches store some entries at 1/100 or 1/1000 of the true count with the
    SAME digits (Meggitt 7,820,200 vs 782,020,000; Micro Focus likewise). An entry more
    than 20x from its security's median is rescaled by the power of ten that lands it
    within 2x of the median, else dropped. Real consolidations are at most ~15:1, so the
    20x gate cannot touch them; every correction is counted and logged."""
    out = []
    corrections = 0
    for _sid, group in frame.partition_by("security_id", as_dict=True).items():
        counts = sorted(group["shares"].to_list())
        median = counts[len(counts) // 2]
        for row in group.iter_rows(named=True):
            value = row["shares"]
            if median > 0 and (value > 20 * median or value < median / 20):
                rescued = None
                for power in (100.0, 1000.0, 0.01, 0.001):
                    candidate = value * power
                    if median / 2 <= candidate <= 2 * median:
                        rescued = candidate
                        break
                corrections += 1
                if rescued is None:
                    continue  # dropped: no power-of-ten reading is plausible
                row = {**row, "shares": rescued}
            out.append(row)
    return pl.DataFrame(out, schema=frame.schema).sort(["security_id", "date"]), corrections


def _today() -> date:
    from datetime import UTC, datetime

    return datetime.now(UTC).date()


class SharesSeries:
    """Point-in-time lookup: the latest share count whose availability precedes t."""

    def __init__(self, root: Path) -> None:
        frame = pl.read_parquet(root / "outstanding.parquet").sort(["security_id", "date"])
        self._by_security: dict[str, tuple[list[date], list[float]]] = {}
        for (sid,), group in frame.partition_by("security_id", as_dict=True).items():
            self._by_security[str(sid)] = (
                group["available_from"].to_list(),
                group["shares"].to_list(),
            )

    def outstanding(self, security_id: str, on: date) -> float | None:
        series = self._by_security.get(security_id)
        if series is None:
            return None
        availabilities, counts = series
        index = bisect_right(availabilities, on)
        if index == 0:
            return None
        return counts[index - 1]


if __name__ == "__main__":
    from trp.logging import setup_logging

    setup_logging()
    canonicalise_shares()


def validate_market_caps() -> pl.DataFrame:
    """The QNT-098 harness: market cap for every FTSE 100 member-month (dated shares x
    repaired close in GBP), flagging months outside the plausible member band. The flag
    list IS the adjudication work-list — nothing here fixes anything silently."""
    from datetime import UTC, datetime
    from datetime import time as time_of_day

    from trp.canonical.calendars import get_trading_calendar
    from trp.canonical.fx import FxRates
    from trp.canonical.unit_repair import REPAIRED_SOURCE
    from trp.config import load_settings
    from trp.universe.query import UniverseQuery

    settings = load_settings()
    fx = FxRates(settings.canonical_dir / "fx")
    shares = SharesSeries(settings.canonical_dir / "shares")
    universe_query = UniverseQuery(settings.canonical_dir / "universes")
    prices = (
        pl.read_parquet(settings.canonical_dir / "prices" / "*/part-*.parquet")
        .filter(pl.col("source") == REPAIRED_SOURCE)
        .select("security_id", "trade_date", "close", "currency")
        .sort(["security_id", "trade_date"])
    )
    sessions = get_trading_calendar("XLON").sessions_between(date(2010, 1, 1), _today())
    month_ends = [
        s
        for i, s in enumerate(sessions)
        if i + 1 == len(sessions) or sessions[i + 1].month != s.month
    ]
    rows: list[dict[str, object]] = []
    for end in month_ends:
        as_of = datetime.combine(end, time_of_day(23, 59, 59), tzinfo=UTC)
        members = universe_query.members("FTSE100", end, as_of=as_of)
        window = prices.filter(
            (pl.col("trade_date") <= end) & (pl.col("trade_date") > end - timedelta(days=15))
        )
        latest = window.group_by("security_id").last()
        closes = {
            row["security_id"]: (float(row["close"]), row["currency"])
            for row in latest.iter_rows(named=True)
        }
        for sid in members:
            priced = closes.get(str(sid))
            count = shares.outstanding(str(sid), end)
            if priced is None or count is None:
                continue
            close, unit = priced
            from trp.canonical.price_overrides import PRICE_CURRENCY_OVERRIDES

            override = PRICE_CURRENCY_OVERRIDES.get(str(sid))
            if override is not None:
                unit = override[0]
            if unit == "GBX":
                gbp = close / 100
            elif unit == "GBP":
                gbp = close
            else:
                try:
                    gbp = fx.to_gbp(close, unit, end)
                except Exception:
                    continue
            rows.append(
                {
                    "security_id": str(sid),
                    "date": end,
                    "market_cap_gbp": gbp * count,
                }
            )
    frame = pl.DataFrame(rows)
    flagged = frame.filter((pl.col("market_cap_gbp") < 200e6) | (pl.col("market_cap_gbp") > 350e9))
    return flagged.sort(["security_id", "date"])
