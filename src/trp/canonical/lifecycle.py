"""Lifecycle delisting records (QNT-100): reasons from evidence, never from guesswork.

A security whose repaired price series ended more than SERIES_END_GAP_DAYS before the
dataset edge has left the market. This module turns those endings into canonical
``DelistingAction`` records:

- ex_date: the first XLON session after the last print.
- reason: the curated FTSE history's removal entry where one matches (acquisition/merger
  -> ACQUISITION), a small human adjudication table for the known special cases
  (NMC Health and Thomas Cook were failures; Invesco, Just Eat, Ferguson, CRH and
  Flutter moved exchanges), and otherwise UNKNOWN — which the engine resolves at the
  last traded close, a value that approximates acquisition consideration and
  collapsed-failure value alike (DEC-023). Claiming ACQUISITION without evidence would
  be fabrication; UNKNOWN is the honest label with the same accounting.
- available_at: the ex-date itself (a delisting is public the day it happens), flagged
  imputed because the timestamp is a convention rather than a sourced announcement.

Ticker matching against curated removals is windowed (the removal must sit within
MATCH_WINDOW_DAYS of the last print) so recycled tickers cannot attach the wrong
company's exit; anything ambiguous stays UNKNOWN and is listed in the report.
"""

import json
import logging
from datetime import UTC, date, datetime
from pathlib import Path

import polars as pl

from trp.domain.security import DelistingReason

logger = logging.getLogger(__name__)

SERIES_END_GAP_DAYS = 15
MATCH_WINDOW_DAYS = 400

ADJUDICATED_REASONS: dict[str, tuple[DelistingReason, str]] = {
    "NMC": (DelistingReason.FAILURE, "NMC Health: administration April 2020"),
    "TCG": (DelistingReason.FAILURE, "Thomas Cook: compulsory liquidation Sept 2019"),
    # FTSE 250 members (QNT-111 universe extension):
    "CLLN": (DelistingReason.FAILURE, "Carillion: compulsory liquidation January 2018"),
    "INTU": (DelistingReason.FAILURE, "Intu Properties: administration June 2020"),
    "IVZ": (DelistingReason.EXCHANGE_MOVE, "Invesco: primary listing moved to NYSE 2007"),
    "JET": (DelistingReason.EXCHANGE_MOVE, "Just Eat Takeaway: LSE line ended, AMS primary"),
    "FERG": (DelistingReason.EXCHANGE_MOVE, "Ferguson: primary listing moved to NYSE 2022"),
    "CRH": (DelistingReason.EXCHANGE_MOVE, "CRH: primary listing moved to NYSE 2023"),
    "FLTR": (DelistingReason.EXCHANGE_MOVE, "Flutter: primary listing moved to NYSE 2024"),
}

_ACQUISITION_REASONS = {"acquisition", "merger"}


def _curated_removals() -> list[tuple[date, str, str]]:
    """(effective, ticker, reason) for every curated removal carrying a reason —
    FTSE 100 curated history plus the FTSE 250 constituent-history corporate-event
    rows (QNT-111), whose deleted names are mapped to tickers via the resolution file."""
    from importlib.resources import files

    doc = json.loads((files("trp.universe") / "data" / "ftse100_history.json").read_text("utf-8"))
    out = []
    for change in doc["changes"]:
        effective = date.fromisoformat(change["effective"])
        for removed in change.get("removed", []):
            reason = removed.get("reason")
            if reason:
                out.append((effective, str(removed.get("ticker", "")), str(reason)))

    ftse250_changes = Path("data_sources/ftse/ftse250_changes_raw.json")
    ftse250_resolution = Path("data_sources/ftse/ftse250_resolution.json")
    if ftse250_changes.exists() and ftse250_resolution.exists():
        from trp.universe.ftse250_curate import NameMatcher

        aliases = json.loads(Path("data_sources/ftse/ftse250_name_aliases.json").read_text())
        matcher = NameMatcher(aliases)
        resolution = json.loads(ftse250_resolution.read_text())["resolution"]
        ticker_by_canon = {
            canon: str(entry["eodhd_code"]).partition(".")[0]
            for canon, entry in resolution.items()
            if entry.get("eodhd_code")
        }
        for row in json.loads(ftse250_changes.read_text()):
            notes = str(row.get("notes", "")).lower()
            deleted = str(row.get("deleted", ""))
            if not deleted or not notes:
                continue
            if "acquisition" in notes or "cash offer" in notes or "offer for" in notes:
                reason = "acquisition"
            elif "merger" in notes:
                reason = "merger"
            else:
                continue
            ticker = ticker_by_canon.get(matcher.canon(deleted))
            if ticker:
                out.append((date.fromisoformat(str(row["effective"])), ticker, reason))
    return out


def build_delistings() -> pl.DataFrame:
    from trp.canonical.calendars import get_trading_calendar
    from trp.canonical.security_store import read_security_master
    from trp.canonical.unit_repair import REPAIRED_SOURCE
    from trp.config import load_settings
    from trp.universe.ftse_build import _eodhd_code_pairs

    settings = load_settings()
    prices = (
        pl.read_parquet(
            settings.canonical_dir / "prices" / "*/part-*.parquet",
            columns=["security_id", "trade_date", "source"],
        )
        .filter(pl.col("source") == REPAIRED_SOURCE)
        .group_by("security_id")
        .agg(pl.col("trade_date").max().alias("last_trade"))
    )
    newest = prices["last_trade"].max()
    master = read_security_master(settings.canonical_dir / "securities")
    tickers_of: dict[str, list[str]] = {}
    for security_id, code in _eodhd_code_pairs(master):
        tickers_of.setdefault(security_id, []).append(code.partition(".")[0])
    removals = _curated_removals()
    calendar = get_trading_calendar("XLON")

    rows: list[dict[str, object]] = []
    for row in prices.iter_rows(named=True):
        security_id, last_trade = row["security_id"], row["last_trade"]
        if (newest - last_trade).days <= SERIES_END_GAP_DAYS:
            continue  # still trading
        tickers = tickers_of.get(security_id, [])
        reason = DelistingReason.UNKNOWN
        provenance = "no curated evidence; UNKNOWN resolves at last close (DEC-023)"
        adjudicated = next(
            (ADJUDICATED_REASONS[t] for t in tickers if t in ADJUDICATED_REASONS), None
        )
        if adjudicated is not None:
            reason, provenance = adjudicated
        else:
            matches = [
                (effective, curated_reason)
                for effective, ticker, curated_reason in removals
                if ticker in tickers
                and abs((effective - last_trade).days) <= MATCH_WINDOW_DAYS
                and curated_reason in _ACQUISITION_REASONS
            ]
            if len({m[1] for m in matches}) == 1:
                reason = DelistingReason.ACQUISITION
                effective, curated_reason = matches[0]
                provenance = (
                    f"curated removal {effective} reason={curated_reason} "
                    f"(within {MATCH_WINDOW_DAYS}d of last print)"
                )
        ex_date = calendar.next_trading_day(last_trade)
        rows.append(
            {
                "security_id": security_id,
                "ex_date": ex_date,
                "last_trading_date": last_trade,
                "reason": reason.value,
                "available_at": datetime.combine(ex_date, datetime.min.time(), tzinfo=UTC),
                "available_at_imputed": True,
                "provenance": provenance,
                "source": "lifecycle-qnt-100",
            }
        )
    frame = pl.DataFrame(rows).sort("ex_date")
    logger.info(
        "lifecycle delistings: %d records (%s)",
        frame.height,
        dict(frame.group_by("reason").len().iter_rows()),
    )
    return frame


def write_delistings() -> Path:
    from trp.config import load_settings

    frame = build_delistings()
    target = load_settings().canonical_dir / "corporate_actions" / "lifecycle_delistings.parquet"
    frame.write_parquet(target)
    return target


def load_delisting_actions(actions_dir: Path) -> list:  # type: ignore[type-arg]
    from trp.domain.corporate_actions import DelistingAction
    from trp.domain.identifiers import SecurityId

    path = actions_dir / "lifecycle_delistings.parquet"
    if not path.exists():
        return []
    actions = []
    for row in pl.read_parquet(path).iter_rows(named=True):
        actions.append(
            DelistingAction(
                security_id=SecurityId(row["security_id"]),
                ex_date=row["ex_date"],
                last_trading_date=row["last_trading_date"],
                reason=DelistingReason(row["reason"]),
                available_at=row["available_at"],
                available_at_imputed=True,
                source=row["source"],
            )
        )
    return actions


if __name__ == "__main__":
    from trp.logging import setup_logging

    setup_logging()
    print(write_delistings())
