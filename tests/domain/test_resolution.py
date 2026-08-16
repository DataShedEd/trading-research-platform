from datetime import date

import pytest

from trp.domain.identifier_map import IdentifierRecord
from trp.domain.identifiers import IdentifierKind, SecurityId, new_entity_id, new_security_id
from trp.domain.master import SecurityMaster
from trp.domain.resolution import (
    AmbiguousIdentifier,
    IdentifierResolver,
    UnknownIdentifier,
)
from trp.domain.security import Entity, Security, SecurityType

CHANGE = date(2022, 1, 25)  # A renames ALPHA → AONE
RECYCLE = date(2023, 6, 1)  # B starts using the abandoned ALPHA ticker


def ticker(
    security_id: SecurityId,
    value: str,
    valid_from: date,
    valid_to: date | None = None,
    mic: str = "XLON",
) -> IdentifierRecord:
    return IdentifierRecord(
        security_id=security_id,
        kind=IdentifierKind.TICKER,
        value=value,
        mic=mic,
        valid_from=valid_from,
        valid_to=valid_to,
        source="test",
    )


def build() -> tuple[IdentifierResolver, SecurityId, SecurityId, SecurityId]:
    ids = [new_security_id() for _ in range(3)]
    a, b, c = ids
    entity_ids = [new_entity_id() for _ in range(3)]
    master = SecurityMaster(
        entities=tuple(
            Entity(entity_id=eid, name=f"Company {i}", country="GB")
            for i, eid in enumerate(entity_ids)
        ),
        securities=tuple(
            Security(
                security_id=sid,
                entity_id=eid,
                security_type=SecurityType.ORDINARY,
                name=f"Company {i} ordinary",
            )
            for i, (sid, eid) in enumerate(zip(ids, entity_ids, strict=True))
        ),
        identifiers=(
            ticker(a, "ALPHA", date(2005, 1, 1), CHANGE),
            ticker(a, "AONE", CHANGE),
            ticker(b, "ALPHA", RECYCLE),
            # DUAL is two different securities on two exchanges at the same time.
            ticker(a, "DUAL", date(2010, 1, 1), mic="XNYS"),
            ticker(c, "DUAL", date(2010, 1, 1), mic="XPAR"),
        ),
    )
    return IdentifierResolver(master), a, b, c


def test_resolves_by_date_across_ticker_change() -> None:
    resolver, a, b, _ = build()
    assert resolver.resolve("ALPHA", IdentifierKind.TICKER, date(2010, 6, 1)) == a
    assert resolver.resolve("AONE", IdentifierKind.TICKER, date(2022, 2, 1)) == a
    # After recycling, the same ticker means a different company.
    assert resolver.resolve("ALPHA", IdentifierKind.TICKER, date(2024, 1, 1)) == b


def test_gap_between_uses_is_unknown_not_guessed() -> None:
    resolver, *_ = build()
    with pytest.raises(UnknownIdentifier):
        resolver.resolve("ALPHA", IdentifierKind.TICKER, date(2022, 6, 1))


def test_old_ticker_unknown_after_change() -> None:
    resolver, *_ = build()
    with pytest.raises(UnknownIdentifier):
        resolver.resolve("AONE", IdentifierKind.TICKER, date(2021, 1, 1))


def test_cross_exchange_ambiguity_requires_mic() -> None:
    resolver, a, _, c = build()
    with pytest.raises(AmbiguousIdentifier):
        resolver.resolve("DUAL", IdentifierKind.TICKER, date(2015, 1, 1))
    assert resolver.resolve("DUAL", IdentifierKind.TICKER, date(2015, 1, 1), mic="XNYS") == a
    assert resolver.resolve("DUAL", IdentifierKind.TICKER, date(2015, 1, 1), mic="XPAR") == c


def test_resolve_many_preserves_order_and_reports_failures_as_rows() -> None:
    resolver, a, _, _ = build()
    frame = resolver.resolve_many(
        ["ALPHA", "MISSING", "DUAL"], IdentifierKind.TICKER, date(2015, 1, 1)
    )
    assert frame["value"].to_list() == ["ALPHA", "MISSING", "DUAL"]
    assert frame["security_id"].to_list() == [a, None, None]
    errors = frame["error"].to_list()
    assert errors[0] is None
    assert "MISSING" in errors[1]  # not found
    assert "matches 2" in errors[2]  # ambiguous without mic

    with pytest.raises(UnknownIdentifier):
        resolver.resolve_many(
            ["ALPHA", "MISSING"], IdentifierKind.TICKER, date(2015, 1, 1), strict=True
        )


def test_identifiers_for_returns_in_force_records() -> None:
    resolver, a, _, _ = build()
    before = resolver.identifiers_for(a, date(2010, 6, 1), IdentifierKind.TICKER)
    assert {r.value for r in before} == {"ALPHA", "DUAL"}
    after = resolver.identifiers_for(a, date(2023, 1, 1), IdentifierKind.TICKER)
    assert {r.value for r in after} == {"AONE", "DUAL"}
