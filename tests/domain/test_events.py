from datetime import date

import pytest
from pydantic import ValidationError

from trp.domain import (
    Acquisition,
    DelistingReason,
    Entity,
    EntityRename,
    ExchangeMove,
    IdentifierKind,
    IdentifierRecord,
    IdentifierResolver,
    Listing,
    Security,
    SecurityId,
    SecurityMaster,
    SecurityStatus,
    SecurityStatusPeriod,
    SecurityType,
    apply_event,
    new_entity_id,
    new_security_id,
    status_on,
)
from trp.domain.changes import Delisting

LISTED = date(2005, 7, 20)


def build(n: int = 1) -> tuple[SecurityMaster, list[SecurityId]]:
    entity_ids = [new_entity_id() for _ in range(n)]
    security_ids = [new_security_id() for _ in range(n)]
    master = SecurityMaster(
        entities=tuple(
            Entity(entity_id=eid, name=f"Company {i} plc", country="GB")
            for i, eid in enumerate(entity_ids)
        ),
        securities=tuple(
            Security(
                security_id=sid,
                entity_id=eid,
                security_type=SecurityType.ORDINARY,
                name=f"Company {i} ordinary",
            )
            for i, (sid, eid) in enumerate(zip(security_ids, entity_ids, strict=True))
        ),
        listings=tuple(
            Listing(security_id=sid, mic="XLON", currency="GBX", valid_from=LISTED)
            for sid in security_ids
        ),
        status_periods=tuple(
            SecurityStatusPeriod(security_id=sid, status=SecurityStatus.ACTIVE, valid_from=LISTED)
            for sid in security_ids
        ),
        identifiers=tuple(
            IdentifierRecord(
                security_id=sid,
                kind=IdentifierKind.TICKER,
                value=f"TK{i}",
                mic="XLON",
                valid_from=LISTED,
                source="test",
            )
            for i, sid in enumerate(security_ids)
        ),
    )
    return master, security_ids


def test_entity_rename_updates_label_only() -> None:
    master, _ = build()
    entity_id = master.entities[0].entity_id
    renamed = apply_event(
        master,
        EntityRename(entity_id=entity_id, new_name="Renamed plc", effective=LISTED, source="t"),
    )
    assert renamed.entities[0].name == "Renamed plc"
    assert renamed.entities[0].entity_id == entity_id
    assert renamed.securities == master.securities


def test_exchange_move_closes_old_venue_and_opens_new() -> None:
    master, (sid,) = build()
    moved = apply_event(
        master,
        ExchangeMove(
            security_id=sid,
            from_mic="XLON",
            to_mic="XNYS",
            currency="USD",
            ticker="TKUS",
            effective=date(2015, 3, 2),
            source="test",
        ),
    )
    old = next(li for li in moved.listings if li.mic == "XLON")
    new = next(li for li in moved.listings if li.mic == "XNYS")
    assert old.valid_to == date(2015, 3, 2)
    assert old.delisting_reason is DelistingReason.EXCHANGE_MOVE
    assert new.valid_from == date(2015, 3, 2) and new.valid_to is None
    resolver = IdentifierResolver(moved)
    assert resolver.resolve("TK0", IdentifierKind.TICKER, date(2010, 1, 1)) == sid
    assert resolver.resolve("TKUS", IdentifierKind.TICKER, date(2016, 1, 1)) == sid


def test_acquisition_links_acquirer_and_preserves_history() -> None:
    master, (target, acquirer) = build(2)
    acquired = apply_event(
        master,
        Acquisition(
            security_id=target,
            acquirer_security_id=acquirer,
            effective=date(2021, 10, 27),
            source="test",
        ),
    )
    terminal = next(
        p
        for p in acquired.status_periods
        if p.security_id == target and p.status is SecurityStatus.ACQUIRED
    )
    assert terminal.related_security_id == acquirer
    assert status_on(acquired, target, date(2020, 1, 1)) is SecurityStatus.ACTIVE
    assert status_on(acquired, acquirer, date(2022, 1, 1)) is SecurityStatus.ACTIVE


def test_delisting_reason_maps_failure_to_liquidated() -> None:
    master, (sid,) = build()
    dead = apply_event(
        master,
        Delisting(
            security_id=sid,
            reason=DelistingReason.FAILURE,
            effective=date(2018, 1, 15),
            source="test",
        ),
    )
    assert status_on(dead, sid, date(2018, 2, 1)) is SecurityStatus.LIQUIDATED


def test_cross_table_invariant_rejects_activity_past_termination() -> None:
    master, (sid,) = build()
    terminal = SecurityStatusPeriod(
        security_id=sid,
        status=SecurityStatus.DELISTED,
        valid_from=date(2018, 1, 15),
    )
    # Listing and identifiers still open-ended past the terminal date → inconsistent.
    with pytest.raises(ValidationError, match="extends past its terminal status date"):
        SecurityMaster(
            entities=master.entities,
            securities=master.securities,
            listings=master.listings,
            status_periods=(*master.status_periods, terminal),
            identifiers=master.identifiers,
        )
