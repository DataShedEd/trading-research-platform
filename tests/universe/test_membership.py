from datetime import date
from pathlib import Path

import polars as pl
import pytest

from tests.universe.conftest import build_ftse100
from trp.domain.identifiers import new_security_id
from trp.universe.membership import (
    MembershipOverlapError,
    UniverseMembership,
    UnknownUniverseError,
    check_memberships,
    register_universe,
    registered_universes,
)
from trp.universe.storage import (
    UniverseStorageError,
    close_open_spell,
    read_universe,
    write_universe,
)


def spell(valid_from: date, valid_to: date | None, sid: object = None) -> UniverseMembership:
    return UniverseMembership(
        universe="FTSE100",
        security_id=sid or new_security_id(),  # type: ignore[arg-type]
        valid_from=valid_from,
        valid_to=valid_to,
        source="test",
    )


def test_unregistered_universe_name_rejected() -> None:
    with pytest.raises(UnknownUniverseError, match="unknown universe"):
        UniverseMembership(
            universe="FTSE_100_TYPO",
            security_id=new_security_id(),
            valid_from=date(2020, 1, 1),
            source="test",
        )
    register_universe("CUSTOM_TEST_UNIVERSE")
    assert "CUSTOM_TEST_UNIVERSE" in registered_universes()


def test_overlap_detection_and_legal_shapes() -> None:
    sid = new_security_id()
    touching = [spell(date(2010, 1, 1), date(2015, 6, 1), sid), spell(date(2015, 6, 1), None, sid)]
    check_memberships(touching)  # adjacent: legal

    disjoint = [
        spell(date(2010, 1, 1), date(2015, 6, 1), sid),
        spell(date(2019, 6, 24), None, sid),
    ]
    check_memberships(disjoint)  # re-entry: two spells, legal

    for bad_start, bad_end in [
        (date(2010, 1, 1), date(2015, 6, 1)),  # identical
        (date(2011, 1, 1), date(2012, 1, 1)),  # contained
        (date(2014, 1, 1), date(2016, 1, 1)),  # straddling
    ]:
        with pytest.raises(MembershipOverlapError, match="overlapping spells"):
            check_memberships(
                [spell(date(2010, 1, 1), date(2015, 6, 1), sid), spell(bad_start, bad_end, sid)]
            )


def test_storage_round_trip_and_determinism(tmp_path: Path) -> None:
    records, ids = build_ftse100()
    path = write_universe(records, tmp_path, known_security_ids=set(ids.values()))
    loaded = read_universe(tmp_path, "FTSE100")
    assert set(loaded) == set(records)
    assert next(r for r in loaded if r.valid_to is None and r.security_id == ids["current"])

    first_bytes = path.read_bytes()
    write_universe(records, tmp_path, known_security_ids=set(ids.values()))
    assert path.read_bytes() == first_bytes  # wholesale rewrite is byte-identical


def test_orphaned_security_rejected(tmp_path: Path) -> None:
    records, ids = build_ftse100()
    with pytest.raises(UniverseStorageError, match="not in the security master"):
        write_universe(records, tmp_path, known_security_ids={ids["current"]})


def test_overlapping_records_unwritable(tmp_path: Path) -> None:
    sid = new_security_id()
    bad = [spell(date(2010, 1, 1), None, sid), spell(date(2012, 1, 1), None, sid)]
    with pytest.raises(MembershipOverlapError):
        write_universe(bad, tmp_path, known_security_ids={sid})


def test_close_open_spell_is_the_only_mutation_path() -> None:
    sid = new_security_id()
    records = [spell(date(2010, 1, 1), None, sid)]
    closed = close_open_spell(records, sid, "FTSE100", date(2020, 6, 22))
    assert closed[0].valid_to == date(2020, 6, 22)
    with pytest.raises(UniverseStorageError, match="no open spell"):
        close_open_spell(list(closed), sid, "FTSE100", date(2021, 1, 1))


def test_null_valid_to_is_a_genuine_null_on_disk(tmp_path: Path) -> None:
    records, ids = build_ftse100()
    path = write_universe(records, tmp_path, known_security_ids=set(ids.values()))
    frame = pl.read_parquet(path)
    assert frame.filter(pl.col("valid_to").is_null()).height == 3
