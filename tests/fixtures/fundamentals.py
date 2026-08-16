"""Shared fundamental-record fixtures, reused by the QNT-020/022/025 suites."""

from datetime import UTC, date, datetime
from decimal import Decimal

from trp.domain.fundamentals import FundamentalValue, PeriodType, StatementType
from trp.domain.identifiers import SecurityId, new_security_id

PERIOD_END = date(2019, 12, 31)
FILED = datetime(2020, 3, 12, 7, 0, tzinfo=UTC)  # RNS announcements go out at 07:00
RESTATED_1 = datetime(2020, 9, 1, 7, 0, tzinfo=UTC)
RESTATED_2 = datetime(2021, 3, 10, 7, 0, tzinfo=UTC)


def fundamental(**overrides: object) -> FundamentalValue:
    fields: dict[str, object] = {
        "security_id": new_security_id(),
        "statement": StatementType.INCOME,
        "line_item": "revenue",
        "period_end": PERIOD_END,
        "period_type": PeriodType.ANNUAL,
        "currency": "GBP",
        "value": Decimal("1250000000"),
        "filed_at": FILED,
        "available_at": FILED,
        "source": "test",
    }
    fields.update(overrides)
    return FundamentalValue(**fields)  # type: ignore[arg-type]


def revision_series(security_id: SecurityId | None = None) -> list[FundamentalValue]:
    """Original filing plus two restatements of FY2019 revenue, well-formed."""
    sid = security_id if security_id is not None else new_security_id()
    original = fundamental(security_id=sid, value=Decimal("1250000000"))
    first = fundamental(
        security_id=sid,
        value=Decimal("1180000000"),
        available_at=RESTATED_1,
        revised_at=RESTATED_1,
        revision_sequence=1,
    )
    second = fundamental(
        security_id=sid,
        value=Decimal("1175000000"),
        available_at=RESTATED_2,
        revised_at=RESTATED_2,
        revision_sequence=2,
    )
    return [original, first, second]
