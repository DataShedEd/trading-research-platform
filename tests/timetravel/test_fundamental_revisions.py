"""QNT-022's acceptance windows over the Tesco restatement fixture: what a query
returns before the original filing, between filing and restatement, and after."""

from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path

import pytest

from tests.fixtures.fundamentals import tesco_restatement
from trp.canonical.fundamentals.queries import fundamentals
from trp.canonical.fundamentals.storage import write_fundamentals

pytestmark = pytest.mark.timetravel

BEFORE_FILING = datetime(2014, 8, 1, tzinfo=UTC)
BETWEEN = datetime(2014, 9, 10, tzinfo=UTC)  # investors believed GBP 1,100m here
AFTER = datetime(2014, 10, 1, tzinfo=UTC)


def test_query_windows_around_the_restatement(tmp_path: Path) -> None:
    original, restated = tesco_restatement()
    write_fundamentals([original, restated], tmp_path, source="fixture")
    sid = original.security_id

    before = fundamentals(tmp_path, [sid], ["trading_profit_guidance"], as_of=BEFORE_FILING)
    assert before.is_empty()

    between = fundamentals(tmp_path, [sid], ["trading_profit_guidance"], as_of=BETWEEN)
    assert between.get_column("value").to_list() == [Decimal("1100000000")]
    assert between.get_column("revision_sequence").to_list() == [0]

    after = fundamentals(tmp_path, [sid], ["trading_profit_guidance"], as_of=AFTER)
    assert after.get_column("value").to_list() == [Decimal("850000000")]
    assert after.get_column("revision_sequence").to_list() == [1]
