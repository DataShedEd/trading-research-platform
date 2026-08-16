"""Point-in-time views of the security master.

Two time dimensions, kept distinct:

- **event time** — when a fact was true in the world (``valid_from``/``valid_to``);
- **knowledge time** — when we believed it (``recorded_at``/``superseded_at``).

:func:`known_as_of` reconstructs the master as it stood at a knowledge instant: records
not yet recorded are absent, records already superseded are absent, and records that were
current *then* come back as plain current records. Event-time helpers
(:func:`status_on`, :func:`listings_on`) answer questions within whichever view they are
given — a historical simulation applies both filters: first what was known, then what
was true.
"""

from datetime import date, datetime

from trp.domain.identifier_map import IdentifierRecord
from trp.domain.identifiers import IdentifierKind, SecurityId
from trp.domain.master import SecurityMaster
from trp.domain.ranges import contains
from trp.domain.resolution import IdentifierResolver
from trp.domain.security import EffectiveDated, Listing, SecurityStatus, revalidated_copy


def _visible[R: EffectiveDated](records: tuple[R, ...], at: datetime) -> tuple[R, ...]:
    return tuple(
        r if r.superseded_at is None else revalidated_copy(r, superseded_at=None)
        for r in records
        if (r.recorded_at is None or r.recorded_at <= at)
        and (r.superseded_at is None or r.superseded_at > at)
    )


def known_as_of(master: SecurityMaster, at: datetime) -> SecurityMaster:
    """The master as it stood at knowledge time ``at``.

    Returned records are all current within the view (their supersession, if any,
    happened in that view's future and is cleared). The result revalidates, so every
    knowledge view is internally consistent.
    """
    if at.tzinfo is None:
        raise ValueError("knowledge time must be timezone-aware (UTC)")
    return SecurityMaster(
        entities=master.entities,
        securities=master.securities,
        listings=_visible(master.listings, at),
        status_periods=_visible(master.status_periods, at),
        identifiers=_visible(master.identifiers, at),
    )


class PointInTimeSecurityMaster:
    """The interface downstream consumers (universe engine, factor engine, backtester)
    should use: every query takes both an event date and a mandatory ``as_of`` knowledge
    timestamp. The unfiltered helpers below remain available for data-management tasks
    such as building the master itself.

    Views are cached per ``as_of`` — a backtest holding ``as_of`` fixed pays for the
    knowledge filter once.
    """

    def __init__(self, master: SecurityMaster) -> None:
        self._master = master
        self._views: dict[datetime, SecurityMaster] = {}
        self._resolvers: dict[datetime, IdentifierResolver] = {}

    def view(self, as_of: datetime) -> SecurityMaster:
        if as_of not in self._views:
            self._views[as_of] = known_as_of(self._master, as_of)
        return self._views[as_of]

    def _resolver(self, as_of: datetime) -> IdentifierResolver:
        if as_of not in self._resolvers:
            self._resolvers[as_of] = IdentifierResolver(self.view(as_of))
        return self._resolvers[as_of]

    def resolve(
        self,
        value: str,
        kind: IdentifierKind,
        on: date,
        *,
        as_of: datetime,
        mic: str | None = None,
    ) -> SecurityId:
        return self._resolver(as_of).resolve(value, kind, on, mic=mic)

    def identifiers_for(
        self,
        security_id: SecurityId,
        on: date,
        *,
        as_of: datetime,
        kind: IdentifierKind | None = None,
    ) -> tuple[IdentifierRecord, ...]:
        return self._resolver(as_of).identifiers_for(security_id, on, kind)

    def status_on(
        self, security_id: SecurityId, on: date, *, as_of: datetime
    ) -> SecurityStatus | None:
        return status_on(self.view(as_of), security_id, on)

    def listings_on(
        self, security_id: SecurityId, on: date, *, as_of: datetime
    ) -> tuple[Listing, ...]:
        return listings_on(self.view(as_of), security_id, on)


def status_on(master: SecurityMaster, security_id: SecurityId, on: date) -> SecurityStatus | None:
    """The security's status on event date ``on`` per current records, or None."""
    for period in master.status_periods:
        if (
            period.is_current
            and period.security_id == security_id
            and contains(period.valid_from, period.valid_to, on)
        ):
            return period.status
    return None


def listings_on(master: SecurityMaster, security_id: SecurityId, on: date) -> tuple[Listing, ...]:
    """Listings in force for the security on event date ``on`` per current records."""
    return tuple(
        listing
        for listing in master.listings
        if listing.is_current
        and listing.security_id == security_id
        and contains(listing.valid_from, listing.valid_to, on)
    )
