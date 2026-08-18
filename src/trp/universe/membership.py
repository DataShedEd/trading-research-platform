"""Time-indexed universe membership — the antidote to survivorship bias.

A universe is never a list; it is a set of membership *spells*: (universe, security,
[valid_from, valid_to)) with mandatory provenance. Records reuse the platform's
bitemporal `EffectiveDated` base (DEC-008), so knowledge time (`recorded_at` /
`superseded_at`) composes exactly as it does in the security master: a membership row
backfilled later is invisible to an earlier `as_of`.

Re-entry is normal (demoted 2015, promoted 2019 = two spells, never one merged span);
the invariant is non-overlap per (universe, security), never uniqueness. Universe names
are registered centrally so a typo cannot create a silently empty universe.
"""

from collections import defaultdict
from collections.abc import Iterable, Sequence
from datetime import date, datetime
from typing import Self

from pydantic import Field, model_validator

from trp.domain.identifiers import SecurityId
from trp.domain.ranges import first_overlap
from trp.domain.security import EffectiveDated

_REGISTERED: set[str] = {
    "FTSE100",
    "FTSE250",
    "FTSE350",
    "UK_ALL_ORDINARY",
    "SP500",
}

# Research coverage: the earliest date factor research and backtests may use each
# universe from (DEC-014). Membership remains queryable earlier as event truth, but data
# completeness is only guaranteed — and gated (QNT-041) — from these dates.
_RESEARCH_COVERAGE_START: dict[str, date] = {
    "FTSE100": date(2010, 1, 1),  # DEC-014: pre-2010 EODHD delisted gap
}


def research_coverage_start(universe: str) -> date | None:
    """The DEC-014 research floor for a universe, or None if not yet declared."""
    if universe not in _REGISTERED:
        raise UnknownUniverseError(universe)
    return _RESEARCH_COVERAGE_START.get(universe)


class UnknownUniverseError(Exception):
    def __init__(self, name: str) -> None:
        super().__init__(
            f"unknown universe {name!r}; registered: {sorted(_REGISTERED)} "
            "(register_universe adds new names — a typo must not become an empty universe)"
        )


class MembershipOverlapError(Exception):
    pass


def register_universe(name: str) -> None:
    _REGISTERED.add(name)


def registered_universes() -> frozenset[str]:
    return frozenset(_REGISTERED)


class UniverseMembership(EffectiveDated):
    universe: str
    security_id: SecurityId
    source: str = Field(min_length=1, description="provider, curated file, or generating rule")

    @model_validator(mode="after")
    def _registered_name(self) -> Self:
        if self.universe not in _REGISTERED:
            raise UnknownUniverseError(self.universe)
        return self


def check_memberships(records: Sequence[UniverseMembership]) -> None:
    """Non-overlap per (universe, security) among current records; raises naming both rows."""
    grouped: dict[tuple[str, str], list[UniverseMembership]] = defaultdict(list)
    for record in records:
        if record.is_current:
            grouped[(record.universe, record.security_id)].append(record)
    for (universe, security_id), spells in grouped.items():
        hit = first_overlap((s.valid_from, s.valid_to) for s in spells)
        if hit is not None:
            i, j = hit
            raise MembershipOverlapError(
                f"{universe}/{security_id}: overlapping spells "
                f"{spells[i].valid_from}..{spells[i].valid_to} and "
                f"{spells[j].valid_from}..{spells[j].valid_to}"
            )


def visible_as_of(
    records: Iterable[UniverseMembership], as_of: datetime | None
) -> tuple[UniverseMembership, ...]:
    """Knowledge filter (QUANT_PRINCIPLES §1): rows recorded after ``as_of`` are absent,
    rows superseded before it are absent. ``as_of=None`` means all current knowledge."""
    if as_of is None:
        return tuple(r for r in records if r.is_current)
    if as_of.tzinfo is None:
        raise ValueError("as_of must be timezone-aware (UTC)")
    return tuple(
        r
        for r in records
        if (r.recorded_at is None or r.recorded_at <= as_of)
        and (r.superseded_at is None or r.superseded_at > as_of)
    )
