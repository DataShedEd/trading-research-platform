"""Identifier resolution: (external identifier, date) → internal security.

Resolution never guesses. No match and ambiguous matches are distinct, typed errors —
a mis-mapped identifier silently attaching prices to the wrong company is exactly the class
of bug this module exists to prevent.
"""

from collections import defaultdict
from collections.abc import Sequence
from datetime import date

import polars as pl

from trp.domain.identifier_map import IdentifierRecord
from trp.domain.identifiers import IdentifierKind, SecurityId
from trp.domain.master import SecurityMaster


class ResolutionError(Exception):
    pass


class UnknownIdentifier(ResolutionError):
    def __init__(self, value: str, kind: IdentifierKind, on: date) -> None:
        super().__init__(f"no {kind.value} identifier {value!r} in force on {on}")


class AmbiguousIdentifier(ResolutionError):
    def __init__(
        self, value: str, kind: IdentifierKind, on: date, candidates: set[SecurityId]
    ) -> None:
        self.candidates = candidates
        super().__init__(
            f"{kind.value} identifier {value!r} on {on} matches "
            f"{len(candidates)} securities: {sorted(candidates)}"
        )


class IdentifierResolver:
    def __init__(self, master: SecurityMaster) -> None:
        self._by_kind_value: dict[tuple[IdentifierKind, str], list[IdentifierRecord]] = defaultdict(
            list
        )
        self._by_security: dict[SecurityId, list[IdentifierRecord]] = defaultdict(list)
        # Superseded records are retained knowledge history, not current truth; resolution
        # over an earlier knowledge state goes through pit.known_as_of first.
        for record in master.identifiers:
            if record.is_current:
                self._by_kind_value[(record.kind, record.value)].append(record)
                self._by_security[record.security_id].append(record)

    def resolve(
        self,
        value: str,
        kind: IdentifierKind,
        on: date,
        *,
        mic: str | None = None,
        provider: str | None = None,
    ) -> SecurityId:
        """Return the security the identifier referred to on ``on``.

        ``mic`` narrows ticker lookups to one exchange; without it, a ticker used by
        different securities on different exchanges on the same date is ambiguous.
        """
        matches = {
            record.security_id
            for record in self._by_kind_value.get((kind, value), [])
            if record.in_force(on)
            and (mic is None or record.mic == mic)
            and (provider is None or record.provider == provider)
        }
        if not matches:
            raise UnknownIdentifier(value, kind, on)
        if len(matches) > 1:
            raise AmbiguousIdentifier(value, kind, on, matches)
        return matches.pop()

    def identifiers_for(
        self, security_id: SecurityId, on: date, kind: IdentifierKind | None = None
    ) -> tuple[IdentifierRecord, ...]:
        """All identifier records in force for a security on ``on``, optionally by kind."""
        return tuple(
            record
            for record in self._by_security.get(security_id, [])
            if record.in_force(on) and (kind is None or record.kind is kind)
        )

    def resolve_many(
        self,
        values: Sequence[str],
        kind: IdentifierKind,
        on: date,
        *,
        mic: str | None = None,
        strict: bool = False,
    ) -> pl.DataFrame:
        """Bulk resolution, preserving input order.

        Returns a frame with columns ``value``, ``security_id``, ``error`` — failures are
        rows, not exceptions, so a caller must consciously handle every unresolved
        identifier instead of silently shrinking its universe. ``strict=True`` raises on
        the first failure instead.
        """
        resolved: list[str | None] = []
        errors: list[str | None] = []
        for value in values:
            try:
                resolved.append(self.resolve(value, kind, on, mic=mic))
                errors.append(None)
            except ResolutionError as exc:
                if strict:
                    raise
                resolved.append(None)
                errors.append(str(exc))
        return pl.DataFrame(
            {"value": list(values), "security_id": resolved, "error": errors},
            schema={"value": pl.Utf8, "security_id": pl.Utf8, "error": pl.Utf8},
        )
