"""QNT-041: the survivorship acceptance gate, run against the REAL dataset.

These tests read `data/canonical/` and therefore skip wherever the dataset is absent
(CI). Locally they are the referee for DEC-014: within research coverage
(2010-01-01 onwards) the FTSE 100 must be fully reconstructable — 100 members on every
rebalance date, every member with price data across its membership, dead companies
present before their exits and absent after. Run explicitly with:

    uv run pytest -m gate -q
"""

from datetime import date, timedelta

import polars as pl
import pytest

from trp.canonical.security_store import read_security_master
from trp.config import Settings
from trp.universe.membership import research_coverage_start
from trp.universe.query import UniverseQuery

SETTINGS = Settings(_env_file=None)
DATA_PRESENT = (SETTINGS.canonical_dir / "universes" / "universe=FTSE100").exists() and (
    SETTINGS.canonical_dir / "prices"
).exists()

pytestmark = [
    pytest.mark.skipif(not DATA_PRESENT, reason="real dataset not present on this machine"),
    pytest.mark.gate,  # excluded from default runs; `uv run pytest -m gate` runs it
    pytest.mark.timetravel,
]

COVERAGE_START = date(2010, 1, 1)

# DEC-016: enumerated, accepted data gaps inside coverage — securities EODHD simply does
# not carry (verified by delisted-list and direct price probes, adjudicated 2026-08-18).
# Together ~2.5% of member-months 2010-2026. A failure NOT in this list still fails the
# gate; shrink this list by finding data, never grow it silently.
KNOWN_DATA_GAPS = {
    "African Barrick Gold ordinary",  # -> Acacia Mining; neither code in EODHD
    "AMEC ordinary",  # -> Amec Foster Wheeler; absent
    "Autonomy Corporation ordinary",  # HP acquisition 2011; absent
    "Cable & Wireless ordinary",  # 2010 demerger lines absent
    "Cadbury Schweppes ordinary",  # exits Feb 2010; 2 member-months affected
    "Essar energy ordinary",  # absent
    "Eurasian Natural Resources Corporation ordinary",  # absent
    "Friends Life Group Limited ordinary",  # Aviva acquisition 2015; absent
    "Home Retail Group ordinary",  # code recycled by Home REIT; original absent
    "ICAP ordinary",  # -> NEX Group; neither era's data present
    "International Power ordinary",  # GDF acquisition 2012; absent
    "Invensys ordinary",  # Schneider acquisition 2014; absent
    "SABMiller ordinary",  # AB InBev 2016; absent — the largest single gap
    "TUI Travel ordinary",  # merged into TUI AG 2014; TT. line absent
    "Worldpay Group ordinary",  # Vantiv acquisition 2018; absent
    "Xstrata ordinary",  # Glencore merger 2013; absent
    "Just Eat plc ordinary",  # prices end 2019-12-24; member to 2020-02-05 (JET line tail)
}
# The gate runs against a static dataset; the effective "now" is the newest bar present.
TOLERANCE = timedelta(days=15)  # holidays + suspension stubs around spell boundaries


@pytest.fixture(scope="module")
def query() -> UniverseQuery:
    return UniverseQuery(SETTINGS.canonical_dir / "universes")


@pytest.fixture(scope="module")
def price_spans() -> dict[str, tuple[date, date]]:
    frame = pl.read_parquet(SETTINGS.canonical_dir / "prices" / "**/*.parquet")
    summary = frame.group_by("security_id").agg(
        pl.col("trade_date").min().alias("first"), pl.col("trade_date").max().alias("last")
    )
    return {
        row["security_id"]: (row["first"], row["last"]) for row in summary.iter_rows(named=True)
    }


@pytest.fixture(scope="module")
def dataset_end(price_spans: dict[str, tuple[date, date]]) -> date:
    return max(last for _, last in price_spans.values())


def month_starts(start: date, end: date) -> list[date]:
    dates, current = [], date(start.year, start.month, 1)
    while current <= end:
        dates.append(current)
        current = (
            date(current.year + 1, 1, 1)
            if current.month == 12
            else date(current.year, current.month + 1, 1)
        )
    return dates


def test_declared_coverage_floor() -> None:
    assert research_coverage_start("FTSE100") == COVERAGE_START


def test_one_hundred_members_on_every_monthly_date(query: UniverseQuery, dataset_end: date) -> None:
    for rebalance in month_starts(COVERAGE_START, dataset_end):
        members = query.members("FTSE100", rebalance)
        assert len(members) == 100, f"{rebalance}: {len(members)} members"


def test_every_member_spell_within_coverage_has_price_data(
    query: UniverseQuery, price_spans: dict[str, tuple[date, date]], dataset_end: date
) -> None:
    """The DEC-014 guarantee itself: no member may be a data ghost inside coverage."""
    master = read_security_master(SETTINGS.canonical_dir / "securities")
    names = {s.security_id: s.name for s in master.securities}
    failures: list[str] = []
    seen: set[str] = set()
    for rebalance in month_starts(COVERAGE_START, dataset_end):
        seen |= query.members("FTSE100", rebalance)
    for security_id in sorted(seen):
        history = query.history("FTSE100", security_id)
        for spell in history:
            overlap_start = max(spell.valid_from, COVERAGE_START)
            overlap_end = min(spell.valid_to or dataset_end, dataset_end)
            if overlap_start >= overlap_end:
                continue
            span = price_spans.get(security_id)
            if span is None:
                failures.append(f"{names[security_id]}: member in coverage, NO price data")
                continue
            first, last = span
            if first > overlap_start + TOLERANCE:
                failures.append(
                    f"{names[security_id]}: prices start {first}, member from {overlap_start}"
                )
            if last < overlap_end - TOLERANCE:
                failures.append(
                    f"{names[security_id]}: prices end {last}, member until {overlap_end}"
                )
    unexpected = [f for f in failures if f.split(":")[0].strip() not in KNOWN_DATA_GAPS]
    assert not unexpected, (
        "coverage holes inside the DEC-014 window that are NOT in the adjudicated "
        "DEC-016 gap list:\n" + "\n".join(unexpected)
    )


def test_dead_companies_present_before_exit_absent_after(query: UniverseQuery) -> None:
    master = read_security_master(SETTINGS.canonical_dir / "securities")
    by_name = {s.name: s.security_id for s in master.securities}

    morrisons = by_name["Wm Morrison Supermarkets PLC ordinary"]
    assert morrisons in query.members("FTSE100", date(2021, 9, 30))  # pre-acquisition
    assert morrisons not in query.members("FTSE100", date(2021, 11, 30))  # post

    # Event truth extends before the research floor: the 2007 index keeps its ghosts.
    hbos = by_name["HBOS ordinary"]
    assert hbos in query.members("FTSE100", date(2007, 8, 15))
    assert all(
        hbos not in query.members("FTSE100", d)
        for d in (date(2010, 1, 1), date(2015, 1, 1), date(2020, 1, 1))
    )


def test_current_membership_is_not_leaking_backwards(query: UniverseQuery) -> None:
    """A 2026 joiner must not appear in 2012 — the failure mode this platform exists
    to prevent, asserted on the real dataset."""
    in_2012 = query.members("FTSE100", date(2012, 8, 15))
    in_2026 = query.members("FTSE100", date(2026, 7, 1))
    joined_since = in_2026 - in_2012
    assert joined_since  # the index turned over; if not, something is deeply wrong
    for security_id in joined_since:
        history = query.history("FTSE100", security_id)
        assert all(s.valid_from > date(2012, 8, 15) or s.valid_to is not None for s in history)
