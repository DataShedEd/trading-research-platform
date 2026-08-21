"""QNT-111 gate: FTSE 250 membership integrity on the real dataset.

Effective-date convention (§4 of the holdout directive): membership changes take
effect at the INDEX EFFECTIVE DATE — the first trading session on which the new
composition applies (FTSE implements at the prior close; an investor replicating the
index trades the change at that open/close). The curated events use exactly the
effective dates printed by FTSE Russell's constituent-history document and review
notices; checkpoint-dated reconciliations are flagged '[unverified]' in their source
strings and bounded by adjacent snapshots.
"""

from datetime import UTC, date, datetime, time, timedelta

import pytest

from trp.config import load_settings
from trp.universe.query import UniverseQuery

pytestmark = pytest.mark.gate

SETTINGS = load_settings()
QUERY = UniverseQuery(SETTINGS.canonical_dir / "universes")

# The curated FTSE 250 span with checkpoint support (QNT-111); QNT-112 sets the
# research coverage start separately (and possibly later).
MEMBERSHIP_START = date(2013, 1, 4)
MEMBERSHIP_END = date(2026, 8, 17)


def monthly_dates() -> list[date]:
    out = []
    day = MEMBERSHIP_START
    while day <= MEMBERSHIP_END:
        out.append(day)
        day = (day.replace(day=1) + timedelta(days=45)).replace(day=1) + timedelta(days=3)
    return out


def test_ftse100_and_ftse250_never_overlap() -> None:
    """FTSE100 ∩ FTSE250 = ∅ at every monthly date under current knowledge."""
    for day in monthly_dates():
        as_of = datetime.combine(day, time(23, 59, 59), tzinfo=UTC)
        overlap = QUERY.members("FTSE100", day, as_of=as_of) & QUERY.members(
            "FTSE250", day, as_of=as_of
        )
        assert not overlap, f"{day}: {sorted(str(s) for s in overlap)[:5]}"


def test_ftse250_count_stays_near_250() -> None:
    """248..252 at every monthly date: exactly 250 minus the enumerated unresolved
    companies' spells (all logged in ftse250_membership_skipped.json) and transient
    corporate-event windows."""
    for day in monthly_dates():
        count = len(QUERY.members("FTSE250", day))
        assert 244 <= count <= 253, f"{day}: {count} members"


def test_promotion_preserves_security_identity() -> None:
    """Royal Mail's 2018 promotion: the SAME security id leaves the 250 and appears in
    the 100 — a transfer, never a delisting or a new identity."""
    before, after = date(2018, 3, 1), date(2018, 4, 3)
    in_250_before = QUERY.members("FTSE250", before)
    in_100_after = QUERY.members("FTSE100", after)
    moved = in_250_before & in_100_after
    assert moved, "no securities moved 250->100 across the March 2018 review"


def test_demotion_preserves_security_identity() -> None:
    """Burberry's September 2024 relegation: same id, opposite direction."""
    before, after = date(2024, 9, 2), date(2024, 10, 1)
    in_100_before = QUERY.members("FTSE100", before)
    in_250_after = QUERY.members("FTSE250", after)
    moved = in_100_before & in_250_after
    assert moved, "no securities moved 100->250 across the September 2024 review"


def test_delisted_ftse250_members_are_preserved() -> None:
    """Survivorship: names that later vanished are still members on their dates —
    Carillion (failed 2018) and Interserve-era names must appear historically."""
    from trp.canonical.security_store import read_security_master

    master = read_security_master(SETTINGS.canonical_dir / "securities")
    names = {str(s.security_id): s.name.lower() for s in master.securities}
    members_2017 = {names.get(str(s), "") for s in QUERY.members("FTSE250", date(2017, 6, 1))}
    assert any("carillion" in n for n in members_2017), "Carillion missing from June 2017"
    members_2015 = {names.get(str(s), "") for s in QUERY.members("FTSE250", date(2015, 3, 2))}
    assert any("aga rangemaster" in n or "amlin" in n for n in members_2015), (
        "known 2015 mid-caps missing"
    )
