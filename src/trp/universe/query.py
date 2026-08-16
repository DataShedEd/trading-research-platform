"""`members(universe, date)` — the only supported way to obtain a universe.

Two time axes, never conflated: ``on`` is the simulated calendar date whose membership is
asked about (event time); ``as_of`` is knowledge time — what we knew when (None = all
current knowledge). The backtester asks for the universe on a rebalance date using only
knowledge available at that same instant.

A date before the universe's coverage raises :class:`UniverseCoverageError` — an empty
set would read as "no members" and a research result quietly computed on an empty
universe is worse than a failed run. Member sets are cached per
(universe, date, as_of, dataset version); canonical data is rewritten wholesale, so the
file mtime is a sufficient version key.
"""

from collections.abc import Sequence
from datetime import date, datetime
from enum import StrEnum
from pathlib import Path

from trp.domain.identifiers import SecurityId
from trp.domain.ranges import contains
from trp.domain.security import FrozenModel
from trp.universe.membership import (
    UniverseMembership,
    UnknownUniverseError,
    registered_universes,
    visible_as_of,
)
from trp.universe.storage import dataset_version, read_universe, stored_universes


class UniverseCoverageError(Exception):
    def __init__(self, universe: str, requested: date, first_covered: date) -> None:
        super().__init__(
            f"universe {universe!r} has no membership data before {first_covered}; "
            f"{requested} cannot be answered — an empty set here would be survivorship "
            "bias by omission"
        )


class ChangeKind(StrEnum):
    ADDED = "added"
    REMOVED = "removed"


class MembershipChange(FrozenModel):
    security_id: SecurityId
    change: ChangeKind
    effective: date
    source: str


class UniverseQuery:
    def __init__(self, root: Path) -> None:
        self._root = root
        self._records: dict[tuple[str, float], tuple[UniverseMembership, ...]] = {}
        self._members: dict[tuple[str, date, datetime | None, float], frozenset[SecurityId]] = {}

    def _load(self, universe: str) -> tuple[tuple[UniverseMembership, ...], float]:
        if universe not in registered_universes():
            raise UnknownUniverseError(universe)
        version = dataset_version(self._root, universe)
        key = (universe, version)
        if key not in self._records:
            self._records[key] = read_universe(self._root, universe)
        return self._records[key], version

    def members(
        self, universe: str, on: date, *, as_of: datetime | None = None
    ) -> frozenset[SecurityId]:
        records, version = self._load(universe)
        cache_key = (universe, on, as_of, version)
        if cache_key not in self._members:
            visible = visible_as_of(records, as_of)
            if not visible or on < min(r.valid_from for r in visible):
                first = min((r.valid_from for r in visible), default=on)
                raise UniverseCoverageError(universe, on, first)
            self._members[cache_key] = frozenset(
                r.security_id for r in visible if contains(r.valid_from, r.valid_to, on)
            )
        return self._members[cache_key]

    def membership_changes(
        self, universe: str, start: date, end: date, *, as_of: datetime | None = None
    ) -> Sequence[MembershipChange]:
        """Additions and removals with effective dates in (start, end], each exactly once.
        Applying them in date order to members(start) reproduces members(end)."""
        records, _ = self._load(universe)
        changes: list[MembershipChange] = []
        for record in visible_as_of(records, as_of):
            if start < record.valid_from <= end:
                changes.append(
                    MembershipChange(
                        security_id=record.security_id,
                        change=ChangeKind.ADDED,
                        effective=record.valid_from,
                        source=record.source,
                    )
                )
            if record.valid_to is not None and start < record.valid_to <= end:
                changes.append(
                    MembershipChange(
                        security_id=record.security_id,
                        change=ChangeKind.REMOVED,
                        effective=record.valid_to,
                        source=record.source,
                    )
                )
        return sorted(changes, key=lambda c: (c.effective, c.change.value, c.security_id))

    def history(self, universe: str, security_id: SecurityId) -> Sequence[UniverseMembership]:
        records, _ = self._load(universe)
        return sorted(
            (r for r in records if r.is_current and r.security_id == security_id),
            key=lambda r: r.valid_from,
        )

    def universes(self) -> Sequence[tuple[str, date, date | None]]:
        """Stored universe names with their covered range (None end = open-ended)."""
        output = []
        for name in stored_universes(self._root):
            records = visible_as_of(read_universe(self._root, name), None)
            if not records:
                continue
            start = min(r.valid_from for r in records)
            ends = [r.valid_to for r in records]
            end = None if any(e is None for e in ends) else max(e for e in ends if e is not None)
            output.append((name, start, end))
        return output
