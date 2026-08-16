"""Time-travel tests: information recorded later must be invisible earlier.

Scenario: a company fails in January 2018, but our data vendor only delivers the delisting
record in March 2018. A simulation at knowledge time February 2018 must still see the
security as an ordinary active listing — that is genuinely what an investor's database
said at the time. Once the delisting is known, it applies at its January *event* date.
"""

from datetime import UTC, date, datetime

import pytest

from trp.domain.changes import apply_termination
from trp.domain.identifier_map import IdentifierRecord
from trp.domain.identifiers import IdentifierKind, SecurityId, new_entity_id, new_security_id
from trp.domain.master import SecurityMaster
from trp.domain.pit import PointInTimeSecurityMaster, known_as_of, listings_on, status_on
from trp.domain.resolution import IdentifierResolver, UnknownIdentifier
from trp.domain.security import (
    DelistingReason,
    Entity,
    Listing,
    Security,
    SecurityStatus,
    SecurityStatusPeriod,
    SecurityType,
)

pytestmark = pytest.mark.timetravel

LISTED = date(1999, 1, 1)
FAILED = date(2018, 1, 15)  # event time of the failure
DELIVERED = datetime(2018, 3, 20, 12, 0, tzinfo=UTC)  # when the vendor told us
BEFORE_DELIVERY = datetime(2018, 2, 1, tzinfo=UTC)
AFTER_DELIVERY = datetime(2018, 4, 1, tzinfo=UTC)


def build() -> tuple[SecurityMaster, SecurityId]:
    entity_id, security_id = new_entity_id(), new_security_id()
    master = SecurityMaster(
        entities=(Entity(entity_id=entity_id, name="Failed plc", country="GB"),),
        securities=(
            Security(
                security_id=security_id,
                entity_id=entity_id,
                security_type=SecurityType.ORDINARY,
                name="Failed plc ordinary",
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
                value="FAIL",
                mic="XLON",
                valid_from=LISTED,
                source="test",
            ),
        ),
    )
    dead = apply_termination(
        master,
        security_id,
        FAILED,
        SecurityStatus.LIQUIDATED,
        DelistingReason.FAILURE,
        detail="compulsory liquidation",
        knowledge_time=DELIVERED,
    )
    return dead, security_id


def test_before_delivery_the_security_still_looks_alive() -> None:
    master, sid = build()
    view = known_as_of(master, BEFORE_DELIVERY)
    # Even though the failure has (in the real world) already happened, our database
    # genuinely believed the company was an active listing.
    assert status_on(view, sid, date(2018, 2, 1)) is SecurityStatus.ACTIVE
    assert listings_on(view, sid, date(2018, 2, 1)) != ()
    assert IdentifierResolver(view).resolve("FAIL", IdentifierKind.TICKER, date(2018, 2, 1)) == sid


def test_after_delivery_the_failure_applies_at_its_event_date() -> None:
    master, sid = build()
    view = known_as_of(master, AFTER_DELIVERY)
    # Once known, the liquidation is effective from its January event date...
    assert status_on(view, sid, date(2018, 2, 1)) is SecurityStatus.LIQUIDATED
    assert listings_on(view, sid, date(2018, 2, 1)) == ()
    with pytest.raises(UnknownIdentifier):
        IdentifierResolver(view).resolve("FAIL", IdentifierKind.TICKER, date(2018, 2, 1))
    # ...while history before the event is untouched (survivorship: the security stays).
    assert status_on(view, sid, date(2017, 6, 1)) is SecurityStatus.ACTIVE
    assert IdentifierResolver(view).resolve("FAIL", IdentifierKind.TICKER, date(2017, 6, 1)) == sid


def test_current_master_agrees_with_latest_knowledge_view() -> None:
    master, sid = build()
    assert status_on(master, sid, date(2018, 2, 1)) is SecurityStatus.LIQUIDATED
    assert status_on(master, sid, date(2017, 6, 1)) is SecurityStatus.ACTIVE


def test_knowledge_views_are_stable_under_replay() -> None:
    master, _ = build()
    # Reconstructing the same knowledge instant twice gives identical views.
    assert known_as_of(master, BEFORE_DELIVERY) == known_as_of(master, BEFORE_DELIVERY)
    # And a view taken exactly at delivery includes the revision.
    at_delivery = known_as_of(master, DELIVERED)
    assert any(p.status is SecurityStatus.LIQUIDATED for p in at_delivery.status_periods)


def test_pit_facade_matrix_over_event_and_knowledge_dates() -> None:
    """Event date and knowledge date vary independently; every cell has a defined answer."""
    master, sid = build()
    pit = PointInTimeSecurityMaster(master)
    expected = {
        # (event date, knowledge time): expected status
        (date(2017, 6, 1), BEFORE_DELIVERY): SecurityStatus.ACTIVE,
        (date(2017, 6, 1), AFTER_DELIVERY): SecurityStatus.ACTIVE,
        (date(2018, 2, 1), BEFORE_DELIVERY): SecurityStatus.ACTIVE,
        (date(2018, 2, 1), AFTER_DELIVERY): SecurityStatus.LIQUIDATED,
        (date(1998, 6, 1), BEFORE_DELIVERY): None,  # before listing: nothing known
    }
    for (on, as_of), status in expected.items():
        assert pit.status_on(sid, on, as_of=as_of) is status, (on, as_of)
    # Resolution through the facade follows the same two axes.
    assert (
        pit.resolve("FAIL", IdentifierKind.TICKER, date(2018, 2, 1), as_of=BEFORE_DELIVERY) == sid
    )
    with pytest.raises(UnknownIdentifier):
        pit.resolve("FAIL", IdentifierKind.TICKER, date(2018, 2, 1), as_of=AFTER_DELIVERY)


def test_naive_knowledge_time_rejected() -> None:
    master, _ = build()
    with pytest.raises(ValueError, match="timezone-aware"):
        known_as_of(master, datetime(2018, 2, 1))  # noqa: DTZ001 — the point of the test
