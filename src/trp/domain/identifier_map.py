"""Effective-dated mapping between external identifiers and internal securities.

A ticker change is two records (old range closed, new range opened), never an update.
Uniqueness invariants are enforced over collections via :func:`find_mapping_conflicts`
because they are properties of the map, not of a single record:

- one external value maps to at most one security at any date;
- a security carries at most one value per (kind, exchange, provider) at any date.
"""

import re
from collections import defaultdict
from collections.abc import Iterable
from datetime import date
from typing import Self

from pydantic import Field, model_validator

from trp.domain.identifier_validation import validate_cusip, validate_isin, validate_sedol
from trp.domain.identifiers import IdentifierKind, SecurityId
from trp.domain.ranges import contains, first_overlap
from trp.domain.security import EffectiveDated

_TICKER_RE = re.compile(r"^[A-Z0-9.]{1,12}$")


class IdentifierRecord(EffectiveDated):
    security_id: SecurityId
    kind: IdentifierKind
    value: str = Field(min_length=1)
    mic: str | None = Field(default=None, pattern=r"^[A-Z0-9]{4}$")
    provider: str | None = None
    source: str = Field(min_length=1)

    @model_validator(mode="after")
    def _validate_by_kind(self) -> Self:
        if self.kind is IdentifierKind.TICKER:
            if self.mic is None:
                raise ValueError("ticker identifiers require an exchange (mic)")
            if not _TICKER_RE.match(self.value):
                raise ValueError(f"ticker {self.value!r}: malformed")
        elif self.kind is IdentifierKind.PROVIDER:
            if self.provider is None:
                raise ValueError("provider identifiers require a provider name")
        elif self.kind is IdentifierKind.ISIN:
            validate_isin(self.value)
        elif self.kind is IdentifierKind.SEDOL:
            validate_sedol(self.value)
        elif self.kind is IdentifierKind.CUSIP:
            validate_cusip(self.value)
        return self

    def in_force(self, on: date) -> bool:
        return contains(self.valid_from, self.valid_to, on)


class MappingConflict(Exception):
    def __init__(self, first: IdentifierRecord, second: IdentifierRecord, reason: str) -> None:
        self.first = first
        self.second = second
        self.reason = reason
        super().__init__(f"{reason}: {first!r} vs {second!r}")


def find_mapping_conflicts(records: Iterable[IdentifierRecord]) -> list[MappingConflict]:
    """Return all pairwise conflicts in an identifier map. Empty list means consistent."""
    by_value: dict[tuple[str, ...], list[IdentifierRecord]] = defaultdict(list)
    by_security: dict[tuple[str, ...], list[IdentifierRecord]] = defaultdict(list)
    for r in records:
        qualifier = (r.kind.value, r.mic or "", r.provider or "")
        by_value[(r.value, *qualifier)].append(r)
        by_security[(r.security_id, *qualifier)].append(r)

    conflicts: list[MappingConflict] = []
    for group in by_value.values():
        for a, b in _overlapping_pairs(group):
            if a.security_id != b.security_id:
                conflicts.append(
                    MappingConflict(a, b, "one external value mapped to two securities at once")
                )
    for group in by_security.values():
        for a, b in _overlapping_pairs(group):
            if a.value != b.value:
                conflicts.append(
                    MappingConflict(a, b, "security holds two values of one kind at once")
                )
    return conflicts


def _overlapping_pairs(
    group: list[IdentifierRecord],
) -> list[tuple[IdentifierRecord, IdentifierRecord]]:
    pairs: list[tuple[IdentifierRecord, IdentifierRecord]] = []
    remaining = list(group)
    while len(remaining) > 1:
        hit = first_overlap((r.valid_from, r.valid_to) for r in remaining)
        if hit is None:
            break
        i, j = hit
        pairs.append((remaining[i], remaining[j]))
        remaining.pop(j)
    return pairs
