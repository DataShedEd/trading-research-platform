"""Parquet persistence for universe membership: one file per universe.

Layout: ``data/canonical/universes/universe=<NAME>/membership.parquet``. Histories are
small (thousands of rows), so one deterministic file per universe beats date partitioning.
Writes validate everything first (registered name, non-overlap, security ids resolve in
the master), stage to a temporary file, and rename — the same universe rewritten from the
same inputs is byte-identical. Existing rows are never edited in place; the one sanctioned
mutation is :func:`close_open_spell`, which returns a NEW record set with the open spell
closed (and, when a knowledge time is given, the original superseded per DEC-008).
"""

from collections.abc import Sequence, Set
from datetime import date, datetime
from pathlib import Path

import polars as pl

from trp.domain.identifiers import SecurityId
from trp.domain.security import revalidated_copy
from trp.universe.membership import (
    UniverseMembership,
    check_memberships,
    registered_universes,
)

MEMBERSHIP_SCHEMA: dict[str, pl.DataType | type[pl.DataType]] = {
    "universe": pl.Utf8,
    "security_id": pl.Utf8,
    "valid_from": pl.Date,
    "valid_to": pl.Date,
    "recorded_at": pl.Datetime(time_unit="us", time_zone="UTC"),
    "superseded_at": pl.Datetime(time_unit="us", time_zone="UTC"),
    "source": pl.Utf8,
}

_SORT = ["universe", "security_id", "valid_from", "recorded_at"]


class UniverseStorageError(Exception):
    pass


def write_universe(
    records: Sequence[UniverseMembership],
    root: Path,
    *,
    known_security_ids: Set[str],
) -> Path:
    """Write one universe's full membership history (wholesale rewrite)."""
    universes = {r.universe for r in records}
    if len(universes) != 1:
        raise UniverseStorageError(f"one universe per write; got {sorted(universes) or 'none'}")
    (universe,) = universes

    check_memberships(records)
    orphans = {r.security_id for r in records} - set(known_security_ids)
    if orphans:
        raise UniverseStorageError(
            f"{universe}: security ids not in the security master: {sorted(orphans)}"
        )

    directory = root / f"universe={universe}"
    directory.mkdir(parents=True, exist_ok=True)
    rows = [r.model_dump(mode="python") for r in records]
    frame = pl.DataFrame(rows, schema=MEMBERSHIP_SCHEMA).sort(_SORT, nulls_last=True)
    tmp = directory / ".membership.parquet.tmp"
    frame.write_parquet(tmp)
    final = directory / "membership.parquet"
    tmp.replace(final)
    return final


def read_universe(root: Path, universe: str) -> tuple[UniverseMembership, ...]:
    path = root / f"universe={universe}" / "membership.parquet"
    if not path.exists():
        raise UniverseStorageError(f"no stored membership for universe {universe!r} under {root}")
    frame = pl.read_parquet(path)
    return tuple(UniverseMembership(**row) for row in frame.iter_rows(named=True))


def stored_universes(root: Path) -> tuple[str, ...]:
    if not root.exists():
        return ()
    names = tuple(
        sorted(
            d.name.split("=", 1)[1]
            for d in root.glob("universe=*")
            if (d / "membership.parquet").exists()
        )
    )
    return names


def dataset_version(root: Path, universe: str) -> float:
    """Cache key component: the membership file's mtime (rewritten wholesale on change)."""
    path = root / f"universe={universe}" / "membership.parquet"
    return path.stat().st_mtime if path.exists() else 0.0


def close_open_spell(
    records: Sequence[UniverseMembership],
    security_id: SecurityId,
    universe: str,
    on: date,
    *,
    knowledge_time: datetime | None = None,
) -> tuple[UniverseMembership, ...]:
    """The one sanctioned way to end an open membership: returns a new record set with the
    open spell closed at ``on`` (half-open: ``on`` is the first day out). With a
    ``knowledge_time`` the original row is kept, superseded, per DEC-008."""
    output: list[UniverseMembership] = []
    closed = False
    for record in records:
        if (
            record.is_current
            and record.universe == universe
            and record.security_id == security_id
            and record.valid_to is None
        ):
            replacement = revalidated_copy(record, valid_to=on)
            if knowledge_time is None:
                output.append(replacement)
            else:
                output.append(revalidated_copy(record, superseded_at=knowledge_time))
                output.append(revalidated_copy(replacement, recorded_at=knowledge_time))
            closed = True
        else:
            output.append(record)
    if not closed:
        raise UniverseStorageError(f"{universe}/{security_id}: no open spell to close on {on}")
    return tuple(output)


def assert_universe_known(universe: str) -> None:
    if universe not in registered_universes():
        from trp.universe.membership import UnknownUniverseError

        raise UnknownUniverseError(universe)
