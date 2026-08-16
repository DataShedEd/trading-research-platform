"""Test-the-test: prove the time-travel assertions actually detect leakage.

A suite that never fails gives false confidence. Here we (a) corrupt the fixture the way
a bad vendor would — a restated value stamped with the ORIGINAL filing's availability —
and (b) implement the classic wrong query that filters on ``period_end`` instead of
``available_at``. In both cases the standard assertions MUST fail; if they ever pass,
this suite fails, in CI.

The corrupted fixture builder lives here, physically separate from the good fixtures,
and is loudly named so it can never be picked up by a normal test.
"""

from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path

import polars as pl
import pytest

from tests.fixtures.fundamentals import tesco_restatement
from tests.timetravel.test_fundamental_asof import assert_no_leakage
from trp.canonical.fundamentals.storage import read_fundamentals, write_fundamentals
from trp.domain.fundamentals import FundamentalValue
from trp.domain.security import revalidated_copy

pytestmark = pytest.mark.timetravel

BETWEEN = datetime(2014, 9, 10, tzinfo=UTC)  # between original filing and restatement


def CORRUPTED_tesco_rows() -> list[FundamentalValue]:
    """DO NOT use outside this file: the restatement's available_at has been moved back
    to the original filing date — exactly the leak QNT-022 forbids."""
    original, restated = tesco_restatement()
    leaky_restatement = revalidated_copy(
        restated,
        available_at=original.available_at,  # the lie
        revised_at=original.available_at,
        filed_at=original.available_at,
    )
    return [original, leaky_restatement]


def wrong_fundamentals_filtering_on_period_end(
    root: Path, security_id: str, line_item: str, as_of: datetime
) -> pl.DataFrame:
    """The classic wrong implementation: 'the period is over, so it must be known'."""
    frame = read_fundamentals(root, security_ids=[security_id], line_items=[line_item])
    knowable_allegedly = frame.filter(
        pl.col("period_end").cast(pl.Datetime(time_zone="UTC")) <= as_of
    )
    return (
        knowable_allegedly.sort("revision_sequence")
        .group_by(["security_id", "statement", "line_item", "period_end", "period_type"])
        .last()
    )


def test_corrupted_fixture_makes_the_between_window_assertion_fail(tmp_path: Path) -> None:
    rows = CORRUPTED_tesco_rows()
    write_fundamentals(rows, tmp_path, source="CORRUPTED")
    from trp.canonical.fundamentals.queries import fundamentals

    between = fundamentals(
        tmp_path, [rows[0].security_id], ["trading_profit_guidance"], as_of=BETWEEN
    )
    # The correct-implementation query cannot detect a lie in the data itself; the
    # WINDOW assertion is what catches it: an investor in September believed 1,100m,
    # but the corrupted data claims they knew 850m. The assertion must fail.
    with pytest.raises(AssertionError):
        assert between.get_column("value").to_list() == [Decimal("1100000000")]


def test_wrong_period_end_implementation_fails_the_leakage_assertion(tmp_path: Path) -> None:
    original, restated = tesco_restatement()
    write_fundamentals([original, restated], tmp_path, source="fixture")

    leaky = wrong_fundamentals_filtering_on_period_end(
        tmp_path, original.security_id, "trading_profit_guidance", BETWEEN
    )
    # The wrong implementation happily returns the restated row (available 22 Sep)
    # for a 10 Sep query — and assert_no_leakage must catch exactly that.
    assert not leaky.is_empty()
    with pytest.raises(AssertionError, match="leaked from the future"):
        assert_no_leakage(leaky, BETWEEN)
