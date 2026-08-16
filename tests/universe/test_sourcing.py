import json
from datetime import date

import pytest

from trp.universe.sourcing import (
    HistoryReplayError,
    replay_index_history,
    spells_from_eodhd_components,
)


def tiny_history(changes: list[dict[str, object]]) -> dict[str, object]:
    """A 3-member 'index' exercising the same rules as the real 100-member one."""
    return {
        "anchor": {
            "date": "2005-06-20",
            "members": [
                {"name": "Alpha plc", "ticker": "ALPH"},
                {"name": "Beta plc", "ticker": "BETA"},
                {"name": "Gamma plc", "ticker": "GAMA"},
            ],
            "source": "test anchor",
        },
        "changes": changes,
    }


def test_replay_produces_correct_spells() -> None:
    history = tiny_history(
        [
            {
                "effective": "2010-03-22",
                "review": "quarterly 2010-Q1",
                "added": [{"name": "Delta plc", "ticker": "DELT"}],
                "removed": [{"name": "Beta plc", "ticker": "BETA", "reason": "review"}],
                "source": "test review",
            },
            {
                "effective": "2018-01-15",
                "review": "ad-hoc",
                "added": [{"name": "Epsilon plc", "ticker": "EPSI"}],
                "removed": [{"name": "Alpha plc", "ticker": "ALPH", "reason": "delisting"}],
                "source": "test delisting",
                "needs_verification": True,
            },
        ]
    )
    spells = replay_index_history(history, expected_size=3, size_tolerance=0)
    by_ticker = {s.ticker: s for s in spells}
    assert by_ticker["BETA"].valid_to == date(2010, 3, 22)  # half-open: first day out
    assert by_ticker["DELT"].valid_from == date(2010, 3, 22)
    assert by_ticker["DELT"].valid_to is None  # still a member
    assert by_ticker["ALPH"].valid_from == date(2005, 6, 20)  # anchor member
    assert by_ticker["ALPH"].valid_to == date(2018, 1, 15)
    assert by_ticker["EPSI"].needs_verification  # flag propagates from the change
    assert not by_ticker["DELT"].needs_verification


def test_removing_a_non_member_names_the_bad_entry() -> None:
    history = tiny_history(
        [
            {
                "effective": "2010-03-22",
                "added": [{"name": "Delta plc", "ticker": "DELT"}],
                "removed": [{"name": "Zeta plc", "ticker": "ZETA"}],
                "source": "test",
            }
        ]
    )
    with pytest.raises(HistoryReplayError, match=r"2010-03-22.*ZETA.*not currently a member"):
        replay_index_history(history, expected_size=3, size_tolerance=0)


def test_adding_an_existing_member_rejected() -> None:
    history = tiny_history(
        [
            {
                "effective": "2010-03-22",
                "added": [{"name": "Alpha plc", "ticker": "ALPH"}],
                "removed": [{"name": "Beta plc", "ticker": "BETA"}],
                "source": "test",
            }
        ]
    )
    with pytest.raises(HistoryReplayError, match="already a member"):
        replay_index_history(history, expected_size=3, size_tolerance=0)


def test_size_drift_caught() -> None:
    history = tiny_history(
        [
            {
                "effective": "2010-03-22",
                "added": [],
                "removed": [{"name": "Beta plc", "ticker": "BETA"}],
                "source": "test",
            }
        ]
    )
    with pytest.raises(HistoryReplayError, match="membership count 2 is outside"):
        replay_index_history(history, expected_size=3, size_tolerance=0)
    # With tolerance 1 the same history is legal (brief 2-member state).
    spells = replay_index_history(history, expected_size=3, size_tolerance=1)
    assert len(spells) == 3


def test_rename_preserves_membership_continuity() -> None:
    history = tiny_history(
        [
            {
                "effective": "2006-05-23",
                "review": "ad-hoc",
                "renamed": [{"from_ticker": "BETA", "to_ticker": "BTTR", "new_name": "Better plc"}],
                "source": "test rename",
            },
            {
                "effective": "2010-03-22",
                "added": [{"name": "Delta plc", "ticker": "DELT"}],
                "removed": [{"name": "Better plc", "ticker": "BTTR"}],
                "source": "test review",
            },
        ]
    )
    spells = replay_index_history(history, expected_size=3, size_tolerance=0)
    old = next(s for s in spells if s.ticker == "BETA")
    new = next(s for s in spells if s.ticker == "BTTR")
    assert old.valid_to == date(2006, 5, 23)
    assert new.valid_from == date(2006, 5, 23)  # contiguous: membership never lapsed
    assert new.valid_to == date(2010, 3, 22)
    assert "rename" in new.source and "renamed to BTTR" in old.source

    orphan = tiny_history(
        [
            {
                "effective": "2006-05-23",
                "renamed": [{"from_ticker": "ZETA", "to_ticker": "ZZZZ"}],
                "source": "test",
            }
        ]
    )
    with pytest.raises(HistoryReplayError, match="cannot rename"):
        replay_index_history(orphan, expected_size=3, size_tolerance=0)


def test_out_of_order_changes_rejected() -> None:
    history = tiny_history(
        [
            {"effective": "2012-01-02", "added": [], "removed": [], "source": "t"},
            {"effective": "2010-03-22", "added": [], "removed": [], "source": "t"},
        ]
    )
    with pytest.raises(HistoryReplayError, match="out of order"):
        replay_index_history(history, expected_size=3, size_tolerance=0)


def test_eodhd_components_parse() -> None:
    payload = json.dumps(
        {
            "General": {"Code": "GSPC"},
            "HistoricalTickerComponents": {
                "0": {
                    "Code": "AA",
                    "Name": "Alcoa",
                    "StartDate": "1957-03-04",
                    "EndDate": "2013-09-23",
                    "IsActiveNow": 0,
                },
                "1": {
                    "Code": "AAPL",
                    "Name": "Apple Inc",
                    "StartDate": "1982-11-30",
                    "EndDate": None,
                    "IsActiveNow": 1,
                },
                "2": {"Code": "NODATE", "Name": "No Start", "StartDate": None},
            },
        }
    ).encode()
    spells = spells_from_eodhd_components(payload, source="eodhd GSPC.INDX 2026-08-16")
    assert len(spells) == 2  # the undated entry is skipped
    alcoa = next(s for s in spells if s.ticker == "AA")
    assert alcoa.valid_to == date(2013, 9, 23)
    apple = next(s for s in spells if s.ticker == "AAPL")
    assert apple.valid_to is None
