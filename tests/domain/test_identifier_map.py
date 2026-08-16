from datetime import date

import pytest
from pydantic import ValidationError

from trp.domain.identifier_map import IdentifierRecord, find_mapping_conflicts
from trp.domain.identifiers import IdentifierKind, SecurityId, new_security_id


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


def test_ticker_requires_exchange() -> None:
    with pytest.raises(ValidationError, match="mic"):
        IdentifierRecord(
            security_id=new_security_id(),
            kind=IdentifierKind.TICKER,
            value="SHEL",
            valid_from=date(2022, 1, 25),
            source="test",
        )


def test_checksums_enforced_at_construction() -> None:
    with pytest.raises(ValidationError, match="ISIN"):
        IdentifierRecord(
            security_id=new_security_id(),
            kind=IdentifierKind.ISIN,
            value="GB0002374007",  # bad check digit
            valid_from=date(2000, 1, 1),
            source="test",
        )


def test_ticker_change_is_two_rows_without_conflict() -> None:
    sec = new_security_id()
    change_day = date(2022, 1, 25)  # e.g. RDSB -> SHEL style rename
    records = [
        ticker(sec, "RDSB", date(2005, 7, 20), change_day),
        ticker(sec, "SHEL", change_day),
    ]
    assert find_mapping_conflicts(records) == []
    assert records[0].in_force(date(2021, 1, 1))
    assert not records[0].in_force(change_day)
    assert records[1].in_force(change_day)


def test_one_value_two_securities_overlapping_is_conflict() -> None:
    records = [
        ticker(new_security_id(), "ABC", date(2010, 1, 1), None),
        ticker(new_security_id(), "ABC", date(2012, 1, 1), None),
    ]
    conflicts = find_mapping_conflicts(records)
    assert len(conflicts) == 1
    assert "two securities" in conflicts[0].reason


def test_recycled_ticker_across_time_is_not_conflict() -> None:
    # Tickers get reused by unrelated companies; disjoint ranges are fine.
    records = [
        ticker(new_security_id(), "ABC", date(2000, 1, 1), date(2010, 1, 1)),
        ticker(new_security_id(), "ABC", date(2015, 1, 1), None),
    ]
    assert find_mapping_conflicts(records) == []


def test_security_with_two_tickers_same_exchange_is_conflict() -> None:
    sec = new_security_id()
    records = [
        ticker(sec, "OLD", date(2010, 1, 1), None),
        ticker(sec, "NEW", date(2015, 1, 1), None),
    ]
    conflicts = find_mapping_conflicts(records)
    assert len(conflicts) == 1
    assert "two values" in conflicts[0].reason


def test_same_ticker_on_two_exchanges_is_not_conflict() -> None:
    sec = new_security_id()
    records = [
        ticker(sec, "DUAL", date(2010, 1, 1), mic="XLON"),
        ticker(sec, "DUAL", date(2010, 1, 1), mic="XNYS"),
    ]
    assert find_mapping_conflicts(records) == []
