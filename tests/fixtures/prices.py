"""Shared daily-bar fixtures, reused by the QNT-018 and QNT-019 suites."""

from collections.abc import Sequence
from datetime import UTC, date, datetime
from decimal import Decimal

from trp.domain.identifiers import SecurityId
from trp.domain.prices import DailyBar

INGESTED = datetime(2020, 12, 31, 18, 0, tzinfo=UTC)
SEC_A = SecurityId("SEC-aaaaaaaa-0000-0000-0000-000000000001")
SEC_B = SecurityId("SEC-bbbbbbbb-0000-0000-0000-000000000002")


def bar(
    trade_date: date,
    close: str,
    *,
    security_id: SecurityId = SEC_A,
    **overrides: object,
) -> DailyBar:
    """A flat bar (o=h=l=c) at ``close``, the shape most checks care about."""
    price = Decimal(close)
    fields: dict[str, object] = {
        "security_id": security_id,
        "trade_date": trade_date,
        "open": price,
        "high": price,
        "low": price,
        "close": price,
        "volume": 1000,
        "currency": "GBX",
        "source": "test",
        "ingested_at": INGESTED,
    }
    fields.update(overrides)
    return DailyBar(**fields)  # type: ignore[arg-type]


def series(
    dates: Sequence[date],
    closes: Sequence[str],
    *,
    security_id: SecurityId = SEC_A,
    volumes: Sequence[int] | None = None,
) -> list[DailyBar]:
    """One bar per (date, close) pair, in the order given."""
    if len(dates) != len(closes):
        raise ValueError("dates and closes must be the same length")
    return [
        bar(
            trade_date,
            close,
            security_id=security_id,
            **({"volume": volumes[i]} if volumes is not None else {}),
        )
        for i, (trade_date, close) in enumerate(zip(dates, closes, strict=True))
    ]
