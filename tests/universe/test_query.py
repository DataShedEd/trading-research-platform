from datetime import date
from pathlib import Path

import pytest

from trp.domain.identifiers import SecurityId
from trp.universe.membership import UnknownUniverseError
from trp.universe.query import ChangeKind, UniverseCoverageError, UniverseQuery


@pytest.fixture
def query(stored_ftse100: tuple[Path, dict[str, SecurityId]]) -> UniverseQuery:
    root, _ = stored_ftse100
    return UniverseQuery(root)


def test_membership_on_spell_boundaries(
    query: UniverseQuery, stored_ftse100: tuple[Path, dict[str, SecurityId]]
) -> None:
    _, ids = stored_ftse100
    # First day in: included. Removal day (half-open): excluded.
    assert ids["reentrant"] in query.members("FTSE100", date(2010, 1, 4))
    assert ids["reentrant"] not in query.members("FTSE100", date(2015, 6, 1))
    assert ids["reentrant"] not in query.members("FTSE100", date(2017, 1, 4))  # between spells
    assert ids["reentrant"] in query.members("FTSE100", date(2019, 6, 24))  # re-entry day


def test_delisted_members_appear_historically(
    query: UniverseQuery, stored_ftse100: tuple[Path, dict[str, SecurityId]]
) -> None:
    _, ids = stored_ftse100
    in_2012 = query.members("FTSE100", date(2012, 8, 15))
    assert ids["delisted"] in in_2012  # the later-failed company IS there in 2012
    assert ids["backfilled"] not in in_2012  # the 2020 joiner is NOT
    today = query.members("FTSE100", date(2024, 1, 2))
    assert ids["delisted"] not in today


def test_unknown_universe_and_coverage_errors(query: UniverseQuery) -> None:
    with pytest.raises(UnknownUniverseError, match="registered"):
        query.members("FTSE_1OO", date(2020, 1, 1))
    with pytest.raises(UniverseCoverageError, match="no membership data before"):
        query.members("FTSE100", date(1998, 1, 1))


def test_changes_replay_reconciles_endpoints(
    query: UniverseQuery, stored_ftse100: tuple[Path, dict[str, SecurityId]]
) -> None:
    start, end = date(2012, 1, 3), date(2021, 1, 4)
    members = set(query.members("FTSE100", start))
    for change in query.membership_changes("FTSE100", start, end):
        if change.change is ChangeKind.ADDED:
            members.add(change.security_id)
        else:
            members.discard(change.security_id)
    assert frozenset(members) == query.members("FTSE100", end)


def test_history_returns_every_spell(
    query: UniverseQuery, stored_ftse100: tuple[Path, dict[str, SecurityId]]
) -> None:
    _, ids = stored_ftse100
    spells = query.history("FTSE100", ids["reentrant"])
    assert [s.valid_from for s in spells] == [date(2010, 1, 4), date(2019, 6, 24)]


def test_universes_reports_coverage(query: UniverseQuery) -> None:
    (listing,) = query.universes()
    name, start, end = listing
    assert name == "FTSE100"
    assert start == date(2001, 3, 1)
    assert end is None  # open-ended members exist
