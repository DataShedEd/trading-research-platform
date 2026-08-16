"""The security master aggregate: all tables plus cross-record invariants.

Single-record validation lives on the models; properties of the *collection* — referential
integrity, non-overlapping status history, identifier-map consistency — are enforced here,
so any fully-constructed ``SecurityMaster`` is internally consistent by definition.
"""

from collections import defaultdict
from datetime import date
from typing import Self

from pydantic import model_validator

from trp.domain.identifier_map import IdentifierRecord, find_mapping_conflicts
from trp.domain.ranges import first_overlap
from trp.domain.security import (
    Entity,
    FrozenModel,
    Listing,
    Security,
    SecurityStatus,
    SecurityStatusPeriod,
)

TERMINAL_STATUSES = frozenset(
    {SecurityStatus.DELISTED, SecurityStatus.ACQUIRED, SecurityStatus.LIQUIDATED}
)


class SecurityMaster(FrozenModel):
    entities: tuple[Entity, ...] = ()
    securities: tuple[Security, ...] = ()
    listings: tuple[Listing, ...] = ()
    status_periods: tuple[SecurityStatusPeriod, ...] = ()
    identifiers: tuple[IdentifierRecord, ...] = ()

    @model_validator(mode="after")
    def _consistent(self) -> Self:
        errors: list[str] = []

        entity_ids = {e.entity_id for e in self.entities}
        if len(entity_ids) != len(self.entities):
            errors.append("duplicate entity_id")
        security_ids = {s.security_id for s in self.securities}
        if len(security_ids) != len(self.securities):
            errors.append("duplicate security_id")

        for sec in self.securities:
            if sec.entity_id not in entity_ids:
                errors.append(f"security {sec.security_id}: unknown entity {sec.entity_id}")
        for name, records in (
            ("listing", self.listings),
            ("status period", self.status_periods),
            ("identifier", self.identifiers),
        ):
            for record in records:
                if record.security_id not in security_ids:
                    errors.append(f"{name}: unknown security {record.security_id}")

        # Overlap and uniqueness invariants apply to *current* records only — superseded
        # records are retained history and may legitimately overlap their replacements.
        by_security: dict[str, list[SecurityStatusPeriod]] = defaultdict(list)
        for period in self.status_periods:
            if period.is_current:
                by_security[period.security_id].append(period)
        for sid, periods in by_security.items():
            if first_overlap((p.valid_from, p.valid_to) for p in periods) is not None:
                errors.append(f"security {sid}: overlapping status periods")

        errors.extend(
            c.reason for c in find_mapping_conflicts(r for r in self.identifiers if r.is_current)
        )

        # Cross-table: nothing may remain in force past a terminal status' effective date.
        terminal_from: dict[str, date] = {}
        for period in self.status_periods:
            if period.is_current and period.status in TERMINAL_STATUSES:
                terminal_from[period.security_id] = min(
                    period.valid_from, terminal_from.get(period.security_id, period.valid_from)
                )
        for label, dated in (("listing", self.listings), ("identifier", self.identifiers)):
            for record in dated:
                ended = terminal_from.get(record.security_id)
                if (
                    record.is_current
                    and ended is not None
                    and (record.valid_to is None or record.valid_to > ended)
                ):
                    errors.append(
                        f"{label} for security {record.security_id} extends past its "
                        f"terminal status date {ended}"
                    )

        if errors:
            raise ValueError("inconsistent security master: " + "; ".join(sorted(set(errors))))
        return self
