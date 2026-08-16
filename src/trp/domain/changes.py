"""Corporate lifecycle events applied to the security master.

Each event type is a frozen model (the shape ingestion will eventually produce);
:func:`apply_event` dispatches to a pure function returning a **new**, fully revalidated
``SecurityMaster`` — an inconsistent state cannot be constructed. Events are additive:
rows are closed by setting ``valid_to``, never deleted or edited beyond that closure.
This is the concrete form of the survivorship rule: a company that failed in 2009 is
still fully described today.

Every application takes a ``knowledge_time`` (when we learned of the event). Revised
records are kept, marked ``superseded_at``; replacements carry ``recorded_at`` — so every
historical knowledge state remains reconstructable via ``pit.known_as_of``. Pass
``knowledge_time=None`` only for initial backfills, where revisions replace destructively.

Duplicate application is rejected with ``ChangeError``, never a silent no-op: a ticker
change to the current value, or any event on an already-terminated security, is an error.
"""

from datetime import date, datetime

from pydantic import Field

from trp.domain.identifier_map import IdentifierRecord
from trp.domain.identifiers import EntityId, IdentifierKind, SecurityId
from trp.domain.master import TERMINAL_STATUSES, SecurityMaster
from trp.domain.ranges import contains
from trp.domain.security import (
    DelistingReason,
    EffectiveDated,
    FrozenModel,
    Listing,
    SecurityStatus,
    SecurityStatusPeriod,
    revalidated_copy,
)


class ChangeError(Exception):
    pass


# --------------------------------------------------------------------------- event types


class SecurityEvent(FrozenModel):
    effective: date
    source: str = Field(min_length=1)


class TickerChange(SecurityEvent):
    security_id: SecurityId
    mic: str
    new_ticker: str


class EntityRename(SecurityEvent):
    entity_id: EntityId
    new_name: str = Field(min_length=1)


class ExchangeMove(SecurityEvent):
    security_id: SecurityId
    from_mic: str
    to_mic: str
    currency: str
    ticker: str


class Delisting(SecurityEvent):
    security_id: SecurityId
    reason: DelistingReason
    detail: str | None = None


class Acquisition(SecurityEvent):
    security_id: SecurityId
    acquirer_security_id: SecurityId | None = None
    acquirer_name: str | None = None


def apply_event(
    master: SecurityMaster,
    event: SecurityEvent,
    knowledge_time: datetime | None = None,
) -> SecurityMaster:
    match event:
        case TickerChange():
            return apply_ticker_change(
                master,
                event.security_id,
                event.mic,
                event.new_ticker,
                event.effective,
                event.source,
                knowledge_time,
            )
        case EntityRename():
            return apply_entity_rename(master, event.entity_id, event.new_name)
        case ExchangeMove():
            return apply_exchange_move(master, event, knowledge_time)
        case Delisting():
            status = (
                SecurityStatus.LIQUIDATED
                if event.reason is DelistingReason.FAILURE
                else SecurityStatus.DELISTED
            )
            return apply_termination(
                master,
                event.security_id,
                event.effective,
                status,
                event.reason,
                detail=event.detail,
                knowledge_time=knowledge_time,
            )
        case Acquisition():
            return apply_termination(
                master,
                event.security_id,
                event.effective,
                SecurityStatus.ACQUIRED,
                DelistingReason.ACQUISITION,
                detail=event.acquirer_name,
                related_security_id=event.acquirer_security_id,
                knowledge_time=knowledge_time,
            )
        case _:
            raise ChangeError(f"unhandled event type {type(event).__name__}")


# ------------------------------------------------------------------------ change helpers


def _require_known(master: SecurityMaster, security_id: SecurityId) -> None:
    if all(s.security_id != security_id for s in master.securities):
        raise ChangeError(f"unknown security {security_id}")


def _require_not_terminated(master: SecurityMaster, security_id: SecurityId, on: date) -> None:
    for period in master.status_periods:
        if (
            period.is_current
            and period.security_id == security_id
            and period.status in TERMINAL_STATUSES
            and period.valid_from <= on
        ):
            raise ChangeError(
                f"security {security_id} already {period.status.value} "
                f"since {period.valid_from}; no changes allowed on {on}"
            )


def _revise[R: EffectiveDated](
    records: tuple[R, ...],
    revisions: dict[int, R],
    knowledge_time: datetime | None,
) -> tuple[R, ...]:
    """Apply revisions by index: supersede-and-append when knowledge_time is known,
    destructive replacement when it is not (initial backfill)."""
    if knowledge_time is None:
        return tuple(revisions.get(i, r) for i, r in enumerate(records))
    superseded = tuple(
        revalidated_copy(r, superseded_at=knowledge_time) if i in revisions else r
        for i, r in enumerate(records)
    )
    replacements = tuple(
        revalidated_copy(rev, recorded_at=knowledge_time) for rev in revisions.values()
    )
    return (*superseded, *replacements)


def _stamp_new[R: EffectiveDated](record: R, knowledge_time: datetime | None) -> R:
    return (
        record if knowledge_time is None else revalidated_copy(record, recorded_at=knowledge_time)
    )


def _current_ticker(
    master: SecurityMaster, security_id: SecurityId, mic: str, on: date
) -> tuple[int, IdentifierRecord] | None:
    current = [
        (i, r)
        for i, r in enumerate(master.identifiers)
        if r.is_current
        and r.security_id == security_id
        and r.kind is IdentifierKind.TICKER
        and r.mic == mic
        and r.in_force(on)
    ]
    if len(current) > 1:  # the aggregate invariant makes this unreachable; fail loudly anyway
        raise ChangeError(f"security {security_id} has multiple tickers on {mic} on {on}")
    return current[0] if current else None


def apply_ticker_change(
    master: SecurityMaster,
    security_id: SecurityId,
    mic: str,
    new_ticker: str,
    effective: date,
    source: str,
    knowledge_time: datetime | None = None,
) -> SecurityMaster:
    """Close the current ticker on ``mic`` at event date ``effective``, open ``new_ticker``."""
    _require_known(master, security_id)
    _require_not_terminated(master, security_id, effective)

    found = _current_ticker(master, security_id, mic, effective)
    if found is None:
        raise ChangeError(f"security {security_id} has no ticker on {mic} in force on {effective}")
    index, old = found
    if old.value == new_ticker:
        raise ChangeError(f"ticker on {mic} is already {new_ticker!r} on {effective}")

    new_record = _stamp_new(
        IdentifierRecord(
            security_id=security_id,
            kind=IdentifierKind.TICKER,
            value=new_ticker,
            mic=mic,
            valid_from=effective,
            source=source,
        ),
        knowledge_time,
    )
    identifiers = _revise(
        master.identifiers, {index: revalidated_copy(old, valid_to=effective)}, knowledge_time
    )
    return revalidated_copy(master, identifiers=(*identifiers, new_record))


def apply_entity_rename(
    master: SecurityMaster, entity_id: EntityId, new_name: str
) -> SecurityMaster:
    """Update an entity's current label. Identity is ``entity_id``; name history as
    effective-dated records is future work (see Entity docstring)."""
    if all(e.entity_id != entity_id for e in master.entities):
        raise ChangeError(f"unknown entity {entity_id}")
    return revalidated_copy(
        master,
        entities=tuple(
            revalidated_copy(e, name=new_name) if e.entity_id == entity_id else e
            for e in master.entities
        ),
    )


def apply_exchange_move(
    master: SecurityMaster,
    move: ExchangeMove,
    knowledge_time: datetime | None = None,
) -> SecurityMaster:
    """Close the listing (and ticker) on ``from_mic`` and open both on ``to_mic``."""
    _require_known(master, move.security_id)
    _require_not_terminated(master, move.security_id, move.effective)

    listing_index = next(
        (
            i
            for i, li in enumerate(master.listings)
            if li.is_current
            and li.security_id == move.security_id
            and li.mic == move.from_mic
            and contains(li.valid_from, li.valid_to, move.effective)
        ),
        None,
    )
    if listing_index is None:
        raise ChangeError(
            f"security {move.security_id} has no listing on {move.from_mic} "
            f"in force on {move.effective}"
        )
    old_listing = master.listings[listing_index]

    listing_revisions = {
        listing_index: revalidated_copy(
            old_listing,
            valid_to=move.effective,
            delisting_reason=DelistingReason.EXCHANGE_MOVE,
        )
    }
    new_listing = _stamp_new(
        Listing(
            security_id=move.security_id,
            mic=move.to_mic,
            currency=move.currency,
            valid_from=move.effective,
        ),
        knowledge_time,
    )

    identifier_revisions: dict[int, IdentifierRecord] = {}
    old_ticker = _current_ticker(master, move.security_id, move.from_mic, move.effective)
    if old_ticker is not None:
        index, record = old_ticker
        identifier_revisions[index] = revalidated_copy(record, valid_to=move.effective)
    new_ticker = _stamp_new(
        IdentifierRecord(
            security_id=move.security_id,
            kind=IdentifierKind.TICKER,
            value=move.ticker,
            mic=move.to_mic,
            valid_from=move.effective,
            source=move.source,
        ),
        knowledge_time,
    )
    return revalidated_copy(
        master,
        listings=(*_revise(master.listings, listing_revisions, knowledge_time), new_listing),
        identifiers=(
            *_revise(master.identifiers, identifier_revisions, knowledge_time),
            new_ticker,
        ),
    )


def apply_termination(
    master: SecurityMaster,
    security_id: SecurityId,
    effective: date,
    status: SecurityStatus,
    reason: DelistingReason,
    detail: str | None = None,
    related_security_id: SecurityId | None = None,
    knowledge_time: datetime | None = None,
) -> SecurityMaster:
    """Delist/acquire/liquidate: close every open range at event date ``effective`` and
    record the terminal status. Nothing is deleted — the security remains fully queryable
    historically (survivorship rule)."""
    if status not in TERMINAL_STATUSES:
        raise ChangeError(f"{status.value} is not a terminal status")
    _require_known(master, security_id)
    _require_not_terminated(master, security_id, effective)
    if related_security_id is not None:
        _require_known(master, related_security_id)

    def affected(record: EffectiveDated, sid: SecurityId) -> bool:
        return (
            record.is_current
            and sid == security_id
            and contains(record.valid_from, record.valid_to, effective)
        )

    listing_revisions = {
        i: revalidated_copy(li, valid_to=effective, delisting_reason=reason)
        for i, li in enumerate(master.listings)
        if affected(li, li.security_id)
    }
    identifier_revisions = {
        i: revalidated_copy(r, valid_to=effective)
        for i, r in enumerate(master.identifiers)
        if affected(r, r.security_id)
    }
    status_revisions = {
        i: revalidated_copy(p, valid_to=effective)
        for i, p in enumerate(master.status_periods)
        if affected(p, p.security_id)
    }
    terminal = _stamp_new(
        SecurityStatusPeriod(
            security_id=security_id,
            status=status,
            valid_from=effective,
            reason=detail if detail is not None else reason.value,
            related_security_id=related_security_id,
        ),
        knowledge_time,
    )
    return revalidated_copy(
        master,
        listings=_revise(master.listings, listing_revisions, knowledge_time),
        identifiers=_revise(master.identifiers, identifier_revisions, knowledge_time),
        status_periods=(
            *_revise(master.status_periods, status_revisions, knowledge_time),
            terminal,
        ),
    )
