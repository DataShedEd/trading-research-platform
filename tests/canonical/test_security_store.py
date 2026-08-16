from datetime import date
from pathlib import Path

import duckdb
import polars as pl
import pytest

from trp.canonical.security_store import (
    duckdb_security_master,
    read_security_master,
    write_security_master,
)
from trp.domain.identifier_map import IdentifierRecord
from trp.domain.identifiers import IdentifierKind, new_entity_id, new_security_id
from trp.domain.master import SecurityMaster
from trp.domain.security import (
    DelistingReason,
    Entity,
    Listing,
    Security,
    SecurityStatus,
    SecurityStatusPeriod,
    SecurityType,
)


@pytest.fixture
def master() -> SecurityMaster:
    """Two securities: one renamed with a ticker change, one delisted after failure."""
    e1, e2 = new_entity_id(), new_entity_id()
    s1, s2 = new_security_id(), new_security_id()
    change = date(2022, 1, 25)
    failure = date(2018, 1, 15)
    return SecurityMaster(
        entities=(
            Entity(entity_id=e1, name="Renamed plc", country="GB"),
            Entity(entity_id=e2, name="Failed plc", country="GB"),
        ),
        securities=(
            Security(
                security_id=s1,
                entity_id=e1,
                security_type=SecurityType.ORDINARY,
                name="Renamed plc ordinary",
            ),
            Security(
                security_id=s2,
                entity_id=e2,
                security_type=SecurityType.ORDINARY,
                name="Failed plc ordinary",
            ),
        ),
        listings=(
            Listing(security_id=s1, mic="XLON", currency="GBX", valid_from=date(2005, 7, 20)),
            Listing(
                security_id=s2,
                mic="XLON",
                currency="GBX",
                valid_from=date(1999, 1, 1),
                valid_to=failure,
                delisting_reason=DelistingReason.FAILURE,
            ),
        ),
        status_periods=(
            SecurityStatusPeriod(
                security_id=s2,
                status=SecurityStatus.ACTIVE,
                valid_from=date(1999, 1, 1),
                valid_to=failure,
            ),
            SecurityStatusPeriod(
                security_id=s2,
                status=SecurityStatus.LIQUIDATED,
                valid_from=failure,
                reason="compulsory liquidation",
            ),
        ),
        identifiers=(
            IdentifierRecord(
                security_id=s1,
                kind=IdentifierKind.TICKER,
                value="OLD",
                mic="XLON",
                valid_from=date(2005, 7, 20),
                valid_to=change,
                source="test",
            ),
            IdentifierRecord(
                security_id=s1,
                kind=IdentifierKind.TICKER,
                value="NEW",
                mic="XLON",
                valid_from=change,
                source="test",
            ),
            IdentifierRecord(
                security_id=s2,
                kind=IdentifierKind.SEDOL,
                value="0263494",
                valid_from=date(1999, 1, 1),
                valid_to=failure,
                source="test",
            ),
        ),
    )


def test_round_trip_preserves_everything(master: SecurityMaster, tmp_path: Path) -> None:
    write_security_master(master, tmp_path / "securities")
    loaded = read_security_master(tmp_path / "securities")
    # Order within tables is not part of identity; compare as sets.
    assert set(loaded.entities) == set(master.entities)
    assert set(loaded.securities) == set(master.securities)
    assert set(loaded.listings) == set(master.listings)
    assert set(loaded.status_periods) == set(master.status_periods)
    assert set(loaded.identifiers) == set(master.identifiers)


def test_writes_are_deterministic(master: SecurityMaster, tmp_path: Path) -> None:
    write_security_master(master, tmp_path / "a")
    write_security_master(master, tmp_path / "b")
    for name in ("entities", "securities", "listings", "status_periods", "identifiers"):
        assert (tmp_path / "a" / f"{name}.parquet").read_bytes() == (
            tmp_path / "b" / f"{name}.parquet"
        ).read_bytes()


def test_empty_master_round_trips(tmp_path: Path) -> None:
    write_security_master(SecurityMaster(), tmp_path / "empty")
    loaded = read_security_master(tmp_path / "empty")
    assert loaded == SecurityMaster()


def test_queryable_with_duckdb(master: SecurityMaster, tmp_path: Path) -> None:
    directory = tmp_path / "securities"
    write_security_master(master, directory)
    con = duckdb.connect()
    count = con.execute(
        "select count(*) from read_parquet(?) where kind = 'ticker'",
        [str(directory / "identifiers.parquet")],
    ).fetchone()
    assert count == (2,)


def test_duckdb_views_answer_identifiers_valid_on_date(
    master: SecurityMaster, tmp_path: Path
) -> None:
    directory = tmp_path / "securities"
    write_security_master(master, directory)
    con = duckdb_security_master(directory)
    on = date(2010, 6, 1)
    rows = con.execute(
        "select value from identifiers "
        "where kind = 'ticker' and valid_from <= ? and (valid_to is null or valid_to > ?) "
        "and superseded_at is null",
        [on, on],
    ).fetchall()
    assert rows == [("OLD",)]
    # Open-ended validity persists as a genuine null, not a sentinel date.
    (nulls,) = con.execute("select count(*) from listings where valid_to is null").fetchone()
    assert nulls == 1


def test_interrupted_write_leaves_no_partial_tables(
    master: SecurityMaster, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    directory = tmp_path / "securities"
    write_security_master(master, directory)
    before = {p.name: p.read_bytes() for p in directory.glob("*.parquet")}

    # Fail mid-run: the fourth table write explodes; the first three were already staged.
    calls = {"n": 0}
    original = pl.DataFrame.write_parquet

    def failing(self: pl.DataFrame, *args: object, **kwargs: object) -> None:
        calls["n"] += 1
        if calls["n"] == 4:
            raise OSError("disk full")
        original(self, *args, **kwargs)  # type: ignore[arg-type]

    monkeypatch.setattr(pl.DataFrame, "write_parquet", failing)
    with pytest.raises(OSError, match="disk full"):
        write_security_master(master, directory)

    after = {p.name: p.read_bytes() for p in directory.glob("*.parquet")}
    assert after == before  # published files untouched
    assert list(directory.glob("*.tmp")) == []  # staging cleaned up


def test_inconsistent_files_fail_loudly_on_load(master: SecurityMaster, tmp_path: Path) -> None:
    directory = tmp_path / "securities"
    write_security_master(master, directory)
    # Corrupt the identifier map: drop the range-close on the old ticker so OLD and NEW overlap.
    identifiers = pl.read_parquet(directory / "identifiers.parquet")
    identifiers = identifiers.with_columns(pl.lit(None, dtype=pl.Date).alias("valid_to"))
    identifiers.write_parquet(directory / "identifiers.parquet")
    with pytest.raises(ValueError, match="inconsistent security master"):
        read_security_master(directory)
