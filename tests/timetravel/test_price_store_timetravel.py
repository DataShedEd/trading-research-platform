"""QNT-018 leakage guard: a reproduction bounded by `as_of` cannot see later ingestions.

The failure this prevents: a provider re-sends corrected history, we ingest it, and a
backtest re-run for an earlier date silently produces different numbers than it did
originally — with nothing in the result to say why.
"""

from datetime import UTC, date, datetime
from decimal import Decimal
from pathlib import Path

import pytest

from tests.fixtures.prices import bar
from trp.canonical.price_store import read_bars, read_prices, write_prices

pytestmark = pytest.mark.timetravel

ORIGINAL_INGEST = datetime(2020, 3, 2, 18, 0, tzinfo=UTC)
REVISION_INGEST = datetime(2021, 6, 1, 9, 0, tzinfo=UTC)
REPRODUCTION_AS_OF = datetime(2020, 12, 31, 23, 59, tzinfo=UTC)


def test_bars_ingested_after_as_of_are_invisible(tmp_path: Path) -> None:
    write_prices(
        [bar(date(2020, 3, 2), "100", ingested_at=ORIGINAL_INGEST)], tmp_path, source="run-1"
    )
    # Later: the provider back-fills days it had originally omitted.
    write_prices(
        [
            bar(date(2020, 3, 3), "101", ingested_at=REVISION_INGEST),
            bar(date(2020, 3, 4), "102", ingested_at=REVISION_INGEST),
        ],
        tmp_path,
        source="run-2",
    )

    reproduced = read_bars(tmp_path, as_of=REPRODUCTION_AS_OF)
    assert [b.trade_date for b in reproduced] == [date(2020, 3, 2)]
    assert len(read_bars(tmp_path)) == 3  # the unbounded read does see them


def test_a_corrected_value_does_not_rewrite_the_earlier_reproduction(tmp_path: Path) -> None:
    """A correction arrives as a *new row*, so the old view is still reconstructable.

    The row key includes `source`, so a corrected bar from another provider coexists with
    the original rather than overwriting it — the append-only property that makes an
    as-of read meaningful in the first place.
    """
    write_prices(
        [bar(date(2020, 3, 2), "100", source="provider-a", ingested_at=ORIGINAL_INGEST)],
        tmp_path,
        source="run-1",
    )
    write_prices(
        [bar(date(2020, 3, 2), "137.5", source="provider-b", ingested_at=REVISION_INGEST)],
        tmp_path,
        source="run-2",
    )

    as_of_then = read_prices(tmp_path, as_of=REPRODUCTION_AS_OF)
    assert as_of_then.get_column("close").to_list() == [Decimal("100")]
    assert read_prices(tmp_path).get_column("close").to_list() == [
        Decimal("100"),
        Decimal("137.5"),
    ]


def test_as_of_is_applied_after_partition_pruning_not_instead_of_it(tmp_path: Path) -> None:
    write_prices(
        [
            bar(date(2019, 6, 1), "90", ingested_at=ORIGINAL_INGEST),
            bar(date(2020, 6, 1), "100", ingested_at=ORIGINAL_INGEST),
            bar(date(2020, 6, 2), "101", ingested_at=REVISION_INGEST),
        ],
        tmp_path,
        source="run-1",
    )
    frame = read_prices(
        tmp_path, start=date(2020, 1, 1), end=date(2020, 12, 31), as_of=REPRODUCTION_AS_OF
    )
    assert frame.get_column("trade_date").to_list() == [date(2020, 6, 1)]
