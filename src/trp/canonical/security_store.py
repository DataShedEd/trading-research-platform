"""Persistence for the security master: five Parquet tables under one directory.

Written with explicit Polars schemas (no type inference) and deterministic row ordering so
identical masters produce byte-identical files. Reading reconstructs domain models, which
re-runs every aggregate invariant — corrupt or inconsistent files fail loudly at load.
"""

from pathlib import Path
from typing import Any

import duckdb
import polars as pl

from trp.domain.identifier_map import IdentifierRecord
from trp.domain.master import SecurityMaster
from trp.domain.security import Entity, Listing, Security, SecurityStatusPeriod

_SCHEMAS: dict[str, dict[str, pl.DataType | type[pl.DataType]]] = {
    "entities": {"entity_id": pl.Utf8, "name": pl.Utf8, "country": pl.Utf8},
    "securities": {
        "security_id": pl.Utf8,
        "entity_id": pl.Utf8,
        "security_type": pl.Utf8,
        "name": pl.Utf8,
    },
    "listings": {
        "security_id": pl.Utf8,
        "mic": pl.Utf8,
        "currency": pl.Utf8,
        "valid_from": pl.Date,
        "valid_to": pl.Date,
        "recorded_at": pl.Datetime(time_unit="us", time_zone="UTC"),
        "superseded_at": pl.Datetime(time_unit="us", time_zone="UTC"),
        "delisting_reason": pl.Utf8,
    },
    "status_periods": {
        "security_id": pl.Utf8,
        "status": pl.Utf8,
        "valid_from": pl.Date,
        "valid_to": pl.Date,
        "recorded_at": pl.Datetime(time_unit="us", time_zone="UTC"),
        "superseded_at": pl.Datetime(time_unit="us", time_zone="UTC"),
        "reason": pl.Utf8,
        "related_security_id": pl.Utf8,
    },
    "identifiers": {
        "security_id": pl.Utf8,
        "kind": pl.Utf8,
        "value": pl.Utf8,
        "mic": pl.Utf8,
        "provider": pl.Utf8,
        "source": pl.Utf8,
        "valid_from": pl.Date,
        "valid_to": pl.Date,
        "recorded_at": pl.Datetime(time_unit="us", time_zone="UTC"),
        "superseded_at": pl.Datetime(time_unit="us", time_zone="UTC"),
    },
}


def write_security_master(master: SecurityMaster, directory: Path) -> None:
    """Write all five tables. Atomic per run: files are written to temporary paths and
    renamed only after every table has been produced, so an interrupted write never
    leaves a partially updated master readable."""
    directory.mkdir(parents=True, exist_ok=True)
    tables: dict[str, tuple[Any, ...]] = {
        "entities": master.entities,
        "securities": master.securities,
        "listings": master.listings,
        "status_periods": master.status_periods,
        "identifiers": master.identifiers,
    }
    staged: list[tuple[Path, Path]] = []
    try:
        for name, records in tables.items():
            schema = _SCHEMAS[name]
            rows = [record.model_dump(mode="python") for record in records]
            df = pl.DataFrame(rows, schema=schema)
            df = df.sort(by=list(schema.keys()), nulls_last=True)
            tmp = directory / f".{name}.parquet.tmp"
            df.write_parquet(tmp)
            staged.append((tmp, directory / f"{name}.parquet"))
    except BaseException:
        for tmp, _ in staged:
            tmp.unlink(missing_ok=True)
        raise
    for tmp, final in staged:
        tmp.replace(final)


def duckdb_security_master(directory: Path) -> duckdb.DuckDBPyConnection:
    """A DuckDB connection with the five tables registered as views.

    Example — identifiers valid on a date::

        con.execute(
            "select * from identifiers "
            "where valid_from <= ? and (valid_to is null or valid_to > ?) "
            "and superseded_at is null",
            [on, on],
        )
    """
    con = duckdb.connect()
    for name in _SCHEMAS:
        # CREATE VIEW cannot be a prepared statement; escape the path literal instead.
        path = str(directory / f"{name}.parquet").replace("'", "''")
        con.execute(f"create view {name} as select * from read_parquet('{path}')")
    return con


def read_security_master(directory: Path) -> SecurityMaster:
    frames = {name: pl.read_parquet(directory / f"{name}.parquet") for name in _SCHEMAS}
    return SecurityMaster(
        entities=tuple(Entity(**row) for row in frames["entities"].iter_rows(named=True)),
        securities=tuple(Security(**row) for row in frames["securities"].iter_rows(named=True)),
        listings=tuple(Listing(**row) for row in frames["listings"].iter_rows(named=True)),
        status_periods=tuple(
            SecurityStatusPeriod(**row) for row in frames["status_periods"].iter_rows(named=True)
        ),
        identifiers=tuple(
            IdentifierRecord(**row) for row in frames["identifiers"].iter_rows(named=True)
        ),
    )
