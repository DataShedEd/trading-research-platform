from datetime import date

import pytest

from trp.domain.changes import ChangeError, apply_termination, apply_ticker_change
from trp.domain.identifier_map import IdentifierRecord
from trp.domain.identifiers import IdentifierKind, SecurityId, new_entity_id, new_security_id
from trp.domain.master import SecurityMaster
from trp.domain.resolution import IdentifierResolver
from trp.domain.security import (
    DelistingReason,
    Entity,
    Listing,
    Security,
    SecurityStatus,
    SecurityStatusPeriod,
    SecurityType,
)

LISTED = date(2005, 7, 20)


def build() -> tuple[SecurityMaster, SecurityId]:
    entity_id, security_id = new_entity_id(), new_security_id()
    master = SecurityMaster(
        entities=(Entity(entity_id=entity_id, name="Test plc", country="GB"),),
        securities=(
            Security(
                security_id=security_id,
                entity_id=entity_id,
                security_type=SecurityType.ORDINARY,
                name="Test plc ordinary",
            ),
        ),
        listings=(Listing(security_id=security_id, mic="XLON", currency="GBX", valid_from=LISTED),),
        status_periods=(
            SecurityStatusPeriod(
                security_id=security_id, status=SecurityStatus.ACTIVE, valid_from=LISTED
            ),
        ),
        identifiers=(
            IdentifierRecord(
                security_id=security_id,
                kind=IdentifierKind.TICKER,
                value="OLD",
                mic="XLON",
                valid_from=LISTED,
                source="test",
            ),
            IdentifierRecord(
                security_id=security_id,
                kind=IdentifierKind.ISIN,
                value="GB0002374006",
                valid_from=LISTED,
                source="test",
            ),
        ),
    )
    return master, security_id


def test_ticker_change_closes_old_and_opens_new() -> None:
    master, sid = build()
    change = date(2020, 3, 2)
    updated = apply_ticker_change(master, sid, "XLON", "NEW", change, source="test")

    resolver = IdentifierResolver(updated)
    assert resolver.resolve("OLD", IdentifierKind.TICKER, date(2010, 1, 1)) == sid
    assert resolver.resolve("NEW", IdentifierKind.TICKER, date(2021, 1, 1)) == sid
    # The original master is untouched.
    assert len(master.identifiers) == 2
    assert len(updated.identifiers) == 3


def test_ticker_change_to_same_value_rejected() -> None:
    master, sid = build()
    with pytest.raises(ChangeError, match="already"):
        apply_ticker_change(master, sid, "XLON", "OLD", date(2020, 3, 2), source="test")


def test_ticker_change_before_listing_rejected() -> None:
    master, sid = build()
    with pytest.raises(ChangeError, match="no ticker"):
        apply_ticker_change(master, sid, "XLON", "NEW", date(2000, 1, 1), source="test")


def test_ticker_change_on_unknown_exchange_rejected() -> None:
    master, sid = build()
    with pytest.raises(ChangeError, match="no ticker"):
        apply_ticker_change(master, sid, "XNYS", "NEW", date(2020, 3, 2), source="test")


def test_termination_closes_all_open_ranges() -> None:
    master, sid = build()
    failure = date(2018, 1, 15)
    updated = apply_termination(
        master,
        sid,
        failure,
        SecurityStatus.LIQUIDATED,
        DelistingReason.FAILURE,
        detail="compulsory liquidation",
    )

    (listing,) = updated.listings
    assert listing.valid_to == failure
    assert listing.delisting_reason is DelistingReason.FAILURE
    assert all(r.valid_to == failure for r in updated.identifiers)
    statuses = {(p.status, p.valid_from, p.valid_to) for p in updated.status_periods}
    assert (SecurityStatus.ACTIVE, LISTED, failure) in statuses
    assert (SecurityStatus.LIQUIDATED, failure, None) in statuses

    # History intact: the ticker still resolves before the failure, not after.
    resolver = IdentifierResolver(updated)
    assert resolver.resolve("OLD", IdentifierKind.TICKER, date(2017, 1, 1)) == sid


def test_no_changes_after_termination() -> None:
    master, sid = build()
    dead = apply_termination(
        master, sid, date(2018, 1, 15), SecurityStatus.LIQUIDATED, DelistingReason.FAILURE
    )
    with pytest.raises(ChangeError, match="already liquidated"):
        apply_ticker_change(dead, sid, "XLON", "ZOMBIE", date(2019, 1, 1), source="test")
    with pytest.raises(ChangeError, match="already liquidated"):
        apply_termination(
            dead, sid, date(2019, 1, 1), SecurityStatus.DELISTED, DelistingReason.VOLUNTARY
        )


def test_termination_requires_terminal_status() -> None:
    master, sid = build()
    with pytest.raises(ChangeError, match="not a terminal status"):
        apply_termination(
            master, sid, date(2018, 1, 15), SecurityStatus.SUSPENDED, DelistingReason.VOLUNTARY
        )
