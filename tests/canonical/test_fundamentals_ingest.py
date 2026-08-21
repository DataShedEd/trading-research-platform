"""QNT-097: EODHD fundamentals extraction and DEC-007 availability decisions."""

from datetime import UTC, date, datetime, timedelta
from decimal import Decimal

import pytest

from trp.canonical.fundamentals.ingest_eodhd import (
    FILING_TRUST_GAP,
    FundamentalsIngestError,
    availability,
    statement_periods,
)
from trp.domain.fundamentals import PeriodType, StatementType


def payload(income_yearly: dict) -> dict:  # type: ignore[type-arg]
    return {"Financials": {"Income_Statement": {"currency_symbol": "GBP", "yearly": income_yearly}}}


def test_extraction_reads_envelope_and_items() -> None:
    doc = payload(
        {
            "2025-02-22": {
                "date": "2025-02-22",
                "filing_date": "2025-02-22",
                "currency_symbol": "GBP",
                "totalRevenue": "69910000000.00",
                "netIncome": "1787000000.00",
                "researchDevelopment": None,  # a null is an absent fact, not a zero
            }
        }
    )
    periods = statement_periods(doc)
    assert len(periods) == 1
    statement, period_type, period_end, filed_at, currency, items = periods[0]
    assert statement is StatementType.INCOME
    assert period_type is PeriodType.ANNUAL
    assert period_end == date(2025, 2, 22)
    assert filed_at is None  # filing_date == period end: the vendor default, not a filing
    assert currency == "GBP"
    assert {i.name: i.value for i in items} == {
        "totalRevenue": Decimal("69910000000.00"),
        "netIncome": Decimal("1787000000.00"),
    }


def test_quarterly_bucket_is_interim_for_uk() -> None:
    doc = {
        "Financials": {
            "Balance_Sheet": {
                "quarterly": {
                    "2024-08-24": {
                        "date": "2024-08-24",
                        "currency_symbol": "GBP",
                        "totalStockholderEquity": "12000000000",
                    }
                }
            }
        }
    }
    ((statement, period_type, *_rest),) = statement_periods(doc)
    assert statement is StatementType.BALANCE
    assert period_type is PeriodType.INTERIM


def test_row_without_currency_inherits_the_statement_level_declaration() -> None:
    """Pre-~2023 EODHD rows carry no per-row currency; the statement envelope's claim
    applies (the fix that recovered 75k historical rows in QNT-097)."""
    doc = payload({"2025-02-22": {"date": "2025-02-22", "totalRevenue": "1"}})
    ((_s, _p, _e, _f, currency, _i),) = statement_periods(doc)
    assert currency == "GBP"  # from the Income_Statement envelope


def test_row_with_no_currency_anywhere_is_dropped() -> None:
    doc = {
        "Financials": {
            "Income_Statement": {
                "yearly": {"2025-02-22": {"date": "2025-02-22", "totalRevenue": "1"}}
            }
        }
    }
    assert statement_periods(doc) == []


def test_unparseable_value_raises_rather_than_coercing() -> None:
    doc = payload(
        {"2025-02-22": {"date": "2025-02-22", "currency_symbol": "GBP", "totalRevenue": "n/a"}}
    )
    with pytest.raises(FundamentalsIngestError, match="not a number"):
        statement_periods(doc)


def test_genuine_filing_date_is_trusted() -> None:
    doc = payload(
        {
            "2024-12-31": {
                "date": "2024-12-31",
                "filing_date": "2025-03-14",  # 73 days later: a real filing
                "currency_symbol": "USD",
                "netIncome": "5",
            }
        }
    )
    ((_s, _pt, _pe, filed_at, *_),) = statement_periods(doc)
    assert filed_at == datetime(2025, 3, 14, tzinfo=UTC)


def test_availability_imputes_conservatively_when_filing_is_the_default() -> None:
    when, imputed, rule = availability(date(2024, 12, 31), PeriodType.ANNUAL, None)
    assert when == datetime(2024, 12, 31, tzinfo=UTC) + timedelta(days=120)
    assert imputed is True
    assert rule == "period_end+120d (UK annual, DEC-007)"
    when_interim, _, rule_interim = availability(date(2024, 6, 30), PeriodType.INTERIM, None)
    assert when_interim == datetime(2024, 6, 30, tzinfo=UTC) + timedelta(days=90)
    assert rule_interim == "period_end+90d (UK interim, DEC-007)"


def test_availability_passes_a_trusted_filing_through() -> None:
    filed = datetime(2025, 3, 14, tzinfo=UTC)
    when, imputed, rule = availability(date(2024, 12, 31), PeriodType.ANNUAL, filed)
    assert when == filed
    assert imputed is False
    assert rule is None


def test_trust_gap_boundary() -> None:
    period_end = date(2024, 12, 31)
    inside = payload(
        {
            "2024-12-31": {
                "date": "2024-12-31",
                "filing_date": (period_end + FILING_TRUST_GAP).isoformat(),
                "currency_symbol": "GBP",
                "netIncome": "5",
            }
        }
    )
    ((_s, _p, _e, filed_at_inside, _c, _i),) = statement_periods(inside)
    assert filed_at_inside is None  # at the gap: still the vendor default
