"""The QNT-035 check layer must not become a back door around the PIT guarantee.

The bake-off checks derive an ``available_at`` for provider statements — from a real
publication timestamp where one exists, otherwise by DEC-007 imputation. That derivation
feeds QNT-020 records, so it inherits the whole point-in-time contract: fed into the as-of
query, nothing derived here may ever be visible before the availability it was given.
"""

import json
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from pathlib import Path
from typing import Any

import polars as pl
import pytest

from trp.bakeoff.checks_pit_fundamentals import DEC007_ASSUMED_LAG_DAYS, derive_available_at
from trp.bakeoff.payloads import StatementRow, parse_statements
from trp.bakeoff.universe.loader import Market
from trp.canonical.fundamentals.queries import fundamentals
from trp.canonical.fundamentals.storage import write_fundamentals
from trp.domain.fundamentals import FundamentalValue, PeriodType, StatementType
from trp.domain.identifiers import SecurityId

pytestmark = pytest.mark.timetravel

SECURITY = SecurityId("SEC-pit-check-expectations")
LINE_ITEM = "revenue"
MARKET = Market.UK


def payload() -> bytes:
    """Three statements: a real filing date, a naive timestamp, and no timestamp at all."""
    statements: list[dict[str, Any]] = [
        {
            "period_end": "2019-12-31",
            "period_type": "annual",
            "currency": "GBP",
            "filed_at": "2020-03-12T07:00:00Z",
            "items": {LINE_ITEM: "1000"},
        },
        {
            "period_end": "2020-12-31",
            "period_type": "annual",
            "currency": "GBP",
            "filed_at": "2021-03-04",
            "items": {LINE_ITEM: "1100"},
        },
        {
            "period_end": "2021-12-31",
            "period_type": "annual",
            "currency": "GBP",
            "items": {LINE_ITEM: "1200"},
        },
    ]
    return json.dumps({"statements": statements}).encode()


def records() -> list[tuple[StatementRow, FundamentalValue]]:
    parsed = parse_statements([payload()])
    built: list[tuple[StatementRow, FundamentalValue]] = []
    for row in parsed.items:
        available_at, imputed, rule = derive_available_at(row, MARKET)
        assert available_at is not None and row.period_end is not None
        built.append(
            (
                row,
                FundamentalValue(
                    security_id=SECURITY,
                    statement=StatementType.INCOME,
                    line_item=LINE_ITEM,
                    period_end=row.period_end,
                    period_type=PeriodType.ANNUAL,
                    currency="GBP",
                    value=Decimal(row.items[LINE_ITEM]),
                    filed_at=row.filed_at,
                    available_at=available_at,
                    source="bakeoff-check-derivation",
                    availability_imputed=imputed,
                    imputation_rule=rule,
                ),
            )
        )
    return built


def stored(tmp_path: Path) -> list[tuple[StatementRow, FundamentalValue]]:
    built = records()
    write_fundamentals([value for _, value in built], tmp_path, source="bakeoff-check-derivation")
    return built


def test_no_derived_record_is_visible_before_its_derived_availability(tmp_path: Path) -> None:
    built = stored(tmp_path)
    for _, value in built:
        just_before = value.available_at - timedelta(microseconds=1)
        frame = fundamentals(tmp_path, [SECURITY], [LINE_ITEM], as_of=just_before)
        assert value.period_end not in frame["period_end"].to_list()
        at = fundamentals(tmp_path, [SECURITY], [LINE_ITEM], as_of=value.available_at)
        assert value.period_end in at["period_end"].to_list()


def test_as_of_queries_never_leak_a_future_availability(tmp_path: Path) -> None:
    stored(tmp_path)
    for as_of in (
        datetime(2019, 12, 31, tzinfo=UTC),
        datetime(2020, 6, 1, tzinfo=UTC),
        datetime(2021, 3, 4, tzinfo=UTC),
        datetime(2026, 1, 1, tzinfo=UTC),
    ):
        frame = fundamentals(tmp_path, [SECURITY], [LINE_ITEM], as_of=as_of)
        leaked = frame.filter(pl.col("available_at") > as_of)
        assert leaked.is_empty(), f"rows leaked from the future: {leaked.to_dicts()}"


def test_derived_availability_never_precedes_the_period_it_reports(tmp_path: Path) -> None:
    for row, value in records():
        assert row.period_end is not None
        assert value.available_at >= datetime.combine(row.period_end, datetime.min.time(), UTC)


def test_imputation_is_late_and_flagged_so_it_cannot_be_mistaken_for_evidence() -> None:
    imputed = [value for row, value in records() if row.publication_at() is None]
    assert imputed, "the fixture must include a statement with no provider timestamp"
    for value in imputed:
        assert value.availability_imputed
        assert value.imputation_rule == "uk-annual-lag-90d"
        lag = DEC007_ASSUMED_LAG_DAYS[MARKET]["annual"]
        assert value.available_at.date() == value.period_end + timedelta(days=lag)
        assert value.filed_at is None  # nothing invented to fill the gap


def test_a_provider_timestamp_is_used_verbatim_not_widened(tmp_path: Path) -> None:
    """A real timestamp is the provider's evidence: the derivation must not move it."""
    real = [(row, value) for row, value in records() if row.publication_at() is not None]
    assert len(real) == 2
    for row, value in real:
        assert value.available_at == row.publication_at()
        assert not value.availability_imputed


def test_the_derivation_declines_to_invent_availability_without_a_period_end() -> None:
    parsed = parse_statements([json.dumps({"statements": [{"items": {LINE_ITEM: "1"}}]}).encode()])
    (row,) = parsed.items
    available_at, imputed, rule = derive_available_at(row, MARKET)
    assert available_at is None and imputed and rule is None


def test_period_end_only_provider_is_never_more_visible_than_its_imputation(
    tmp_path: Path,
) -> None:
    """The worst provider shape: no timestamps anywhere, so every record is imputed late."""
    statements = [
        {
            "period_end": date(year, 12, 31).isoformat(),
            "period_type": "annual",
            "currency": "GBP",
            "items": {LINE_ITEM: str(year)},
        }
        for year in (2019, 2020, 2021)
    ]
    parsed = parse_statements([json.dumps({"statements": statements}).encode()])
    values = []
    for row in parsed.items:
        available_at, imputed, rule = derive_available_at(row, MARKET)
        assert available_at is not None and row.period_end is not None
        values.append(
            FundamentalValue(
                security_id=SECURITY,
                statement=StatementType.INCOME,
                line_item=LINE_ITEM,
                period_end=row.period_end,
                period_type=PeriodType.ANNUAL,
                currency="GBP",
                value=Decimal(row.items[LINE_ITEM]),
                available_at=available_at,
                source="bakeoff-check-derivation",
                availability_imputed=imputed,
                imputation_rule=rule,
            )
        )
    write_fundamentals(values, tmp_path, source="period-end-only")
    # The day after each period end — when a naive pipeline would already show the figure.
    for value in values:
        naive_as_of = datetime.combine(value.period_end, datetime.min.time(), UTC) + timedelta(
            days=1
        )
        frame = fundamentals(tmp_path, [SECURITY], [LINE_ITEM], as_of=naive_as_of)
        assert value.period_end not in frame["period_end"].to_list()
