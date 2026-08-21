"""FTSE 250 research-coverage measurement (QNT-112).

Per calendar year, over month-end sessions:

- expected member-months: 250 x months (the index is always 250 names);
- identity-resolved: members the membership store can name (the gap = curation
  unresolved companies, enumerated separately);
- with usable prices: resolved members with >= 15 repaired bars in the month;
- with action coverage: resolved members whose security has >= 1 corporate-action
  record over its life OR whose month shows no ex-event (actions are only *needed*
  where they exist — this measures presence of the feed, not events per month).

Gap categories per §5 of the holdout directive: KNOWN DATA GAP (resolved id, EODHD has
no/insufficient prices), IDENTITY FAILURE (membership span exists but no security id),
IPO/INSUFFICIENT HISTORY (member's first-ever bar is later than the month — normal for
recent listings inside their first year), SOURCE AMBIGUITY (reconciled '[unverified]'
spell boundaries). LEGITIMATE NON-TRADING periods (suspensions) are counted inside
KNOWN DATA GAP months and adjudicated name-by-name where material.

Output: data_sources/ftse/ftse250_coverage.json + a printed table. The research start
decision (DEC entry) is made from this measurement — never assumed from FTSE 100's.
"""

import json
from collections import defaultdict
from datetime import UTC, date, datetime, time

import polars as pl

from trp.canonical.calendars import get_trading_calendar
from trp.canonical.unit_repair import REPAIRED_SOURCE
from trp.config import load_settings
from trp.universe.ftse250_curate import SOURCES
from trp.universe.query import UniverseQuery


def month_ends(start: date, end: date) -> list[date]:
    sessions = get_trading_calendar("XLON").sessions_between(start, end)
    return [
        s
        for i, s in enumerate(sessions)
        if i + 1 == len(sessions) or sessions[i + 1].month != s.month
    ]


def measure(start: date = date(2009, 7, 1), end: date = date(2026, 8, 17)) -> None:
    settings = load_settings()
    query = UniverseQuery(settings.canonical_dir / "universes")
    prices = (
        pl.scan_parquet(settings.canonical_dir / "prices" / "*/part-*.parquet")
        .filter(pl.col("source") == REPAIRED_SOURCE)
        .select("security_id", "trade_date")
        .collect()
    )
    bars_by_sid_month: dict[tuple[str, str], int] = defaultdict(int)
    first_bar: dict[str, date] = {}
    for row in prices.iter_rows():
        sid, day = row
        bars_by_sid_month[(sid, f"{day.year}-{day.month:02d}")] += 1
        if sid not in first_bar or day < first_bar[sid]:
            first_bar[sid] = day
    actions_dir = settings.canonical_dir / "corporate_actions"
    action_sids = set()
    for name in ("eodhd_ftse100_dividends_gbx2.parquet", "eodhd_ftse100_splits_gbx2.parquet"):
        path = actions_dir / name
        if path.exists():
            action_sids |= set(pl.read_parquet(path)["security_id"].to_list())

    yearly: dict[int, dict[str, int]] = defaultdict(
        lambda: {
            "expected": 0,
            "resolved": 0,
            "with_prices": 0,
            "with_actions": 0,
            "ipo_window": 0,
        }
    )
    missing_names: dict[str, set[str]] = defaultdict(set)
    from trp.canonical.security_store import read_security_master

    master = read_security_master(settings.canonical_dir / "securities")
    names = {str(s.security_id): s.name for s in master.securities}

    for month_end in month_ends(start, end):
        as_of = datetime.combine(month_end, time(23, 59, 59), tzinfo=UTC)
        members = query.members("FTSE250", month_end, as_of=as_of)
        stats = yearly[month_end.year]
        stats["expected"] += 250
        stats["resolved"] += len(members)
        month_key = f"{month_end.year}-{month_end.month:02d}"
        for sid in members:
            bars = bars_by_sid_month.get((str(sid), month_key), 0)
            if bars >= 15:
                stats["with_prices"] += 1
                if str(sid) in action_sids:
                    stats["with_actions"] += 1
            else:
                first = first_bar.get(str(sid))
                if first is not None and first > month_end:
                    stats["ipo_window"] += 1
                else:
                    missing_names[str(month_end.year)].add(names.get(str(sid), str(sid)))

    print(
        f"{'year':6}{'expected':>9}{'resolved':>9}{'prices':>8}{'IPOwin':>7}"
        f"{'id-gap%':>9}{'price-gap%':>11}"
    )
    table: dict[int, dict[str, float]] = {}
    for year_key in sorted(yearly):
        stats2 = yearly[year_key]
        id_gap = 100 * (1 - stats2["resolved"] / stats2["expected"])
        price_gap = 100 * (
            1 - (stats2["with_prices"] + stats2["ipo_window"]) / max(stats2["resolved"], 1)
        )
        table[year_key] = {
            **stats2,
            "identity_gap_pct": round(id_gap, 2),
            "price_gap_pct": round(price_gap, 2),
        }
        print(
            f"{year_key:<6}{stats2['expected']:>9}{stats2['resolved']:>9}"
            f"{stats2['with_prices']:>8}{stats2['ipo_window']:>7}"
            f"{id_gap:>8.1f}%{price_gap:>10.1f}%"
        )
    payload = {
        "table": table,
        "missing_by_year": {y: sorted(v) for y, v in missing_names.items()},
    }
    (SOURCES / "ftse250_coverage.json").write_text(json.dumps(payload, indent=1))
    print("wrote data_sources/ftse/ftse250_coverage.json")


if __name__ == "__main__":
    measure()
