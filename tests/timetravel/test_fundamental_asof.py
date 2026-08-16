"""The core leakage guarantees of the as-of fundamentals query (QNT-025)."""

from datetime import UTC, date, datetime
from decimal import Decimal
from pathlib import Path

import polars as pl
import pytest

from tests.fixtures.fundamentals import fundamental, tesco_restatement
from trp.canonical.fundamentals.queries import fundamentals
from trp.canonical.fundamentals.storage import write_fundamentals
from trp.domain.security import revalidated_copy

pytestmark = pytest.mark.timetravel


def assert_no_leakage(frame: pl.DataFrame, as_of: datetime) -> None:
    """The invariant every result must satisfy. Reused by the test-the-test suite."""
    leaked = frame.filter(pl.col("available_at") > as_of)
    assert leaked.is_empty(), f"rows leaked from the future: {leaked.to_dicts()}"


def test_no_returned_row_postdates_as_of(tmp_path: Path) -> None:
    original, restated = tesco_restatement()
    write_fundamentals([original, restated], tmp_path, source="fixture")
    for as_of in (
        datetime(2014, 9, 10, tzinfo=UTC),
        datetime(2014, 10, 1, tzinfo=UTC),
        datetime(2026, 1, 1, tzinfo=UTC),
    ):
        frame = fundamentals(
            tmp_path, [original.security_id], ["trading_profit_guidance"], as_of=as_of
        )
        assert_no_leakage(frame, as_of)


def test_results_unchanged_by_later_availability_rows(tmp_path: Path) -> None:
    original, restated = tesco_restatement()
    write_fundamentals([original, restated], tmp_path, source="fixture")
    sid = original.security_id
    as_of = datetime(2014, 9, 10, tzinfo=UTC)
    before = fundamentals(tmp_path, [sid], ["trading_profit_guidance"], as_of=as_of)

    # Years later the vendor delivers another restatement — history must not move.
    second_restatement = revalidated_copy(
        restated,
        value=Decimal("837000000"),
        revision_sequence=2,
        available_at=datetime(2014, 10, 23, 6, 0, tzinfo=UTC),
        revised_at=datetime(2014, 10, 23, 6, 0, tzinfo=UTC),
        filed_at=datetime(2014, 10, 23, 6, 0, tzinfo=UTC),
    )
    write_fundamentals([second_restatement], tmp_path, source="fixture-later")
    after = fundamentals(tmp_path, [sid], ["trading_profit_guidance"], as_of=as_of)
    assert after.to_dicts() == before.to_dicts()


def test_multi_period_series_reveals_periods_as_they_become_knowable(tmp_path: Path) -> None:
    sid = fundamental().security_id
    periods = [
        fundamental(
            security_id=sid,
            period_end=date(year, 12, 31),
            available_at=datetime(year + 1, 3, 1, 7, tzinfo=UTC),
            filed_at=None,
            value=Decimal(year),
        )
        for year in (2017, 2018, 2019)
    ]
    write_fundamentals(periods, tmp_path, source="fixture")

    at_2019_jan = fundamentals(
        tmp_path, [sid], ["revenue"], as_of=datetime(2019, 1, 15, tzinfo=UTC)
    )
    # FY2018 ended two weeks ago but is NOT knowable yet; only FY2017 is.
    assert at_2019_jan.get_column("value").to_list() == [Decimal(2017)]

    at_2020_jun = fundamentals(tmp_path, [sid], ["revenue"], as_of=datetime(2020, 6, 1, tzinfo=UTC))
    assert at_2020_jun.get_column("value").to_list() == [
        Decimal(2017),
        Decimal(2018),
        Decimal(2019),
    ]
