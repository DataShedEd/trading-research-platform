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


def tesco_restatement(
    security_id: SecurityId | None = None,
) -> tuple[FundamentalValue, FundamentalValue]:
    """The Tesco 2014 profit overstatement, as a two-revision series.

    Public record (re-verifiable): Tesco plc's trading statement of 29 August 2014 guided
    expected trading profit for the six months ending 23 August 2014 at approximately
    GBP 1,100m. On 22 September 2014 Tesco announced (RNS) that it had identified an
    overstatement of its expected half-year profit of approximately GBP 250m — an
    effective revision to c. GBP 850m. (The interim results of 23 October 2014 later
    quantified the overstatement at GBP 263m.) Figures here are the guidance numbers from
    those two announcements; the fixture's purpose is the *timeline* — an investor between
    29 August and 22 September genuinely believed the higher number.

    Sources: Tesco plc RNS announcements 29 Aug 2014 ("Trading Statement") and
    22 Sep 2014 ("Trading Update"), widely reported (e.g. FT, BBC) on those dates.
    """
    sid = security_id if security_id is not None else new_security_id()
    shared: dict[str, object] = {
        "security_id": sid,
        "statement": StatementType.INCOME,
        "line_item": "trading_profit_guidance",
        "period_end": date(2014, 8, 23),
        "period_type": PeriodType.INTERIM,
        "currency": "GBP",
        "source": "fixture:tesco-rns-2014",
    }
    original = FundamentalValue(
        **shared,  # type: ignore[arg-type]
        value=Decimal("1100000000"),
        filed_at=datetime(2014, 8, 29, 6, 0, tzinfo=UTC),
        available_at=datetime(2014, 8, 29, 6, 0, tzinfo=UTC),
    )
    restated = FundamentalValue(
        **shared,  # type: ignore[arg-type]
        value=Decimal("850000000"),
        filed_at=datetime(2014, 9, 22, 6, 0, tzinfo=UTC),
        available_at=datetime(2014, 9, 22, 6, 0, tzinfo=UTC),
        revised_at=datetime(2014, 9, 22, 6, 0, tzinfo=UTC),
        revision_sequence=1,
    )
    return original, restated


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
