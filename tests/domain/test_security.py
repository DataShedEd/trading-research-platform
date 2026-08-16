from datetime import date

import pytest
from pydantic import ValidationError

from trp.domain.identifiers import new_entity_id, new_security_id
from trp.domain.security import (
    DelistingReason,
    Entity,
    Listing,
    Security,
    SecurityStatus,
    SecurityStatusPeriod,
    SecurityType,
)


def make_security() -> Security:
    return Security(
        security_id=new_security_id(),
        entity_id=new_entity_id(),
        security_type=SecurityType.ORDINARY,
        name="Test plc ordinary shares",
    )


def test_ids_are_unique_and_prefixed() -> None:
    a, b = new_security_id(), new_security_id()
    assert a != b
    assert a.startswith("SEC-")
    assert new_entity_id().startswith("ENT-")


def test_models_are_immutable() -> None:
    sec = make_security()
    with pytest.raises(ValidationError):
        sec.name = "renamed"  # type: ignore[misc]


def test_entity_country_must_be_iso_alpha2() -> None:
    with pytest.raises(ValidationError):
        Entity(entity_id=new_entity_id(), name="Test plc", country="GBR")


def test_effective_range_must_be_positive() -> None:
    with pytest.raises(ValidationError, match="valid_to"):
        SecurityStatusPeriod(
            security_id=new_security_id(),
            status=SecurityStatus.ACTIVE,
            valid_from=date(2020, 1, 1),
            valid_to=date(2020, 1, 1),
        )


def test_listing_validates_mic_and_currency() -> None:
    sec_id = new_security_id()
    listing = Listing(
        security_id=sec_id,
        mic="XLON",
        currency="GBX",
        valid_from=date(2000, 1, 4),
    )
    assert listing.valid_to is None
    with pytest.raises(ValidationError):
        Listing(security_id=sec_id, mic="London", currency="GBP", valid_from=date(2000, 1, 4))
    with pytest.raises(ValidationError):
        Listing(security_id=sec_id, mic="XLON", currency="gbp", valid_from=date(2000, 1, 4))


def test_delisting_reason_requires_closed_range() -> None:
    with pytest.raises(ValidationError, match="delisting_reason"):
        Listing(
            security_id=new_security_id(),
            mic="XLON",
            currency="GBX",
            valid_from=date(2000, 1, 4),
            delisting_reason=DelistingReason.FAILURE,
        )
