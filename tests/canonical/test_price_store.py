from datetime import UTC, date, datetime
from decimal import Decimal
from pathlib import Path

import polars as pl
import pytest

from tests.fixtures.prices import SEC_A, SEC_B, bar
from trp.canonical.price_store import (
    SMALL_PARTITION_ROWS,
    duckdb_prices,
    partition_row_counts,
    read_bars,
    read_prices,
    small_partitions,
    write_prices,
)
from trp.domain.identifiers import SecurityId
from trp.domain.prices import DailyBar


def files_snapshot(root: Path) -> dict[str, bytes]:
    return {str(p.relative_to(root)): p.read_bytes() for p in root.rglob("part-*.parquet")}


def test_round_trip_preserves_decimal_scale_and_temporal_types(tmp_path: Path) -> None:
    pence = bar(
        date(2020, 3, 2),
        "241.500000",
        open=Decimal("240.250000"),
        high=Decimal("245.750000"),
        low=Decimal("239.000000"),
        provider_adjusted_close=Decimal("0.000125"),
    )
    dollars = bar(date(2020, 3, 2), "412875.125000", security_id=SEC_B, currency="USD")
    write_prices([pence, dollars], tmp_path, source="test")

    frame = read_prices(tmp_path)
    values = {row["security_id"]: row for row in frame.to_dicts()}
    assert isinstance(values[SEC_A]["close"], Decimal)
    assert values[SEC_A]["close"] == Decimal("241.5")
    assert values[SEC_A]["low"] == Decimal("239.0")
    assert values[SEC_A]["provider_adjusted_close"] == Decimal("0.000125")
    assert values[SEC_B]["close"] == Decimal("412875.125")

    row = frame.to_dicts()[0]
    assert isinstance(row["trade_date"], date)
    assert not isinstance(row["trade_date"], datetime)
    assert row["ingested_at"].tzinfo is not None

    assert read_bars(tmp_path) == sorted(
        [pence, dollars], key=lambda b: (b.security_id, b.trade_date, b.source)
    )


def test_bars_land_in_year_partitions(tmp_path: Path) -> None:
    write_prices(
        [bar(date(2019, 12, 31), "100"), bar(date(2020, 1, 2), "101")],
        tmp_path,
        source="test",
    )
    assert {p.name for p in tmp_path.glob("trade_year=*")} == {
        "trade_year=2019",
        "trade_year=2020",
    }
    # One ingestion run writes at most one part file per partition it touches.
    assert len(list(tmp_path.rglob("part-*.parquet"))) == 2


def test_reingesting_identical_bars_is_a_no_op(tmp_path: Path) -> None:
    bars = [bar(date(2020, 3, 2), "100"), bar(date(2020, 3, 3), "101")]
    assert write_prices(bars, tmp_path, source="run-1") == 2
    before = files_snapshot(tmp_path)

    assert write_prices(bars, tmp_path, source="run-2") == 0
    assert files_snapshot(tmp_path) == before  # nothing rewritten, nothing added
    assert read_prices(tmp_path).height == 2


def test_overlapping_write_appends_only_new_bars_leaving_history_byte_identical(
    tmp_path: Path,
) -> None:
    first = [bar(date(2020, 3, 2), "100"), bar(date(2020, 3, 3), "101")]
    write_prices(first, tmp_path, source="run-1")
    before = files_snapshot(tmp_path)

    overlapping = [*first, bar(date(2020, 3, 4), "102")]
    assert write_prices(overlapping, tmp_path, source="run-2") == 1
    after = files_snapshot(tmp_path)
    for name, content in before.items():
        assert after[name] == content  # existing part files untouched

    frame = read_prices(tmp_path)
    assert frame.height == 3
    assert frame.get_column("trade_date").to_list() == [
        date(2020, 3, 2),
        date(2020, 3, 3),
        date(2020, 3, 4),
    ]


def test_a_write_touching_2021_leaves_the_2020_partition_alone(tmp_path: Path) -> None:
    write_prices([bar(date(2020, 3, 2), "100")], tmp_path, source="run-1")
    before = files_snapshot(tmp_path)

    write_prices([bar(date(2021, 3, 2), "110")], tmp_path, source="run-2")
    after = files_snapshot(tmp_path)
    assert {k: v for k, v in after.items() if "trade_year=2020" in k} == before


def test_same_security_day_from_two_providers_coexists(tmp_path: Path) -> None:
    # `source` is part of the row key: two providers' views of one bar are two rows to be
    # compared, not a collision storage resolves by silently dropping one.
    write_prices([bar(date(2020, 3, 2), "100", source="provider-a")], tmp_path, source="a")
    write_prices([bar(date(2020, 3, 2), "100.5", source="provider-b")], tmp_path, source="b")

    frame = read_prices(tmp_path)
    assert frame.height == 2
    assert read_prices(tmp_path, sources=["provider-b"]).get_column("close").to_list() == [
        Decimal("100.5")
    ]


def test_interrupted_write_leaves_dataset_unchanged(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    write_prices([bar(date(2020, 3, 2), "100")], tmp_path, source="run-1")
    before = files_snapshot(tmp_path)

    def explode(self: pl.DataFrame, *args: object, **kwargs: object) -> None:
        raise OSError("disk full")

    monkeypatch.setattr(pl.DataFrame, "write_parquet", explode)
    with pytest.raises(OSError, match="disk full"):
        write_prices([bar(date(2020, 3, 3), "101")], tmp_path, source="run-2")
    monkeypatch.undo()

    assert files_snapshot(tmp_path) == before
    assert list(tmp_path.rglob("*.tmp")) == []
    assert read_prices(tmp_path).height == 1


def test_interruption_partway_through_a_multi_year_write_stages_nothing(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    original_write = pl.DataFrame.write_parquet
    calls = {"n": 0}

    def fail_on_second(self: pl.DataFrame, *args: object, **kwargs: object) -> None:
        calls["n"] += 1
        if calls["n"] == 2:
            raise OSError("disk full")
        original_write(self, *args, **kwargs)  # type: ignore[arg-type]

    monkeypatch.setattr(pl.DataFrame, "write_parquet", fail_on_second)
    with pytest.raises(OSError, match="disk full"):
        write_prices(
            [bar(date(2020, 3, 2), "100"), bar(date(2021, 3, 2), "110")],
            tmp_path,
            source="run-1",
        )
    monkeypatch.undo()

    # The first year was staged but never renamed, so the dataset is still empty.
    assert list(tmp_path.rglob("part-*.parquet")) == []
    assert list(tmp_path.rglob("*.tmp")) == []
    assert read_prices(tmp_path).is_empty()


def test_partition_pruning_reads_only_the_years_in_range(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    write_prices(
        [bar(date(year, 6, 1), "100") for year in (2018, 2019, 2020, 2021)],
        tmp_path,
        source="test",
    )

    touched: list[str] = []
    original_read = pl.read_parquet

    def spy(source: object, *args: object, **kwargs: object) -> pl.DataFrame:
        touched.append(str(source))
        return original_read(source, *args, **kwargs)  # type: ignore[arg-type]

    monkeypatch.setattr(pl, "read_parquet", spy)
    frame = read_prices(tmp_path, start=date(2019, 1, 1), end=date(2020, 12, 31))

    assert frame.height == 2
    assert len(touched) == 2
    assert all("trade_year=2019" in p or "trade_year=2020" in p for p in touched)


def test_write_only_reads_the_partitions_it_touches_when_checking_for_duplicates(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    write_prices(
        [bar(date(year, 6, 1), "100") for year in (2018, 2019, 2020)], tmp_path, source="run-1"
    )

    touched: list[str] = []
    original_read = pl.read_parquet

    def spy(source: object, *args: object, **kwargs: object) -> pl.DataFrame:
        touched.append(str(source))
        return original_read(source, *args, **kwargs)  # type: ignore[arg-type]

    monkeypatch.setattr(pl, "read_parquet", spy)
    write_prices([bar(date(2020, 6, 2), "101")], tmp_path, source="run-2")

    assert touched  # the anti-join did happen
    assert all("trade_year=2020" in p for p in touched)


def test_as_of_hides_bars_ingested_later(tmp_path: Path) -> None:
    early = bar(date(2020, 3, 2), "100", ingested_at=datetime(2020, 3, 2, 18, tzinfo=UTC))
    revision = bar(
        date(2020, 3, 3),
        "101",
        source="provider-b",
        ingested_at=datetime(2021, 1, 5, 18, tzinfo=UTC),
    )
    write_prices([early, revision], tmp_path, source="test")

    as_of = datetime(2020, 6, 1, tzinfo=UTC)
    assert read_prices(tmp_path, as_of=as_of).get_column("trade_date").to_list() == [
        date(2020, 3, 2)
    ]
    assert read_prices(tmp_path).height == 2


def test_as_of_must_be_timezone_aware(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="timezone-aware"):
        read_prices(tmp_path, as_of=datetime(2020, 6, 1))  # noqa: DTZ001 — the point of the test


def test_reading_an_empty_root_returns_the_declared_schema(tmp_path: Path) -> None:
    frame = read_prices(tmp_path / "nothing-here")
    assert frame.is_empty()
    assert frame.columns[:3] == ["security_id", "trade_date", "open"]


def test_ingestion_log_records_every_write_including_no_ops(tmp_path: Path) -> None:
    bars = [bar(date(2020, 3, 2), "100")]
    write_prices(bars, tmp_path, source="backfill-2026-08")
    write_prices(bars, tmp_path, source="backfill-2026-09")

    log = (tmp_path / "_ingestion_log.jsonl").read_text().strip().splitlines()
    assert len(log) == 2
    assert '"source": "backfill-2026-08"' in log[0]
    assert '"rows_written": 1' in log[0]
    assert '"rows_written": 0' in log[1]


def test_partition_row_counts_and_small_partition_reporting(tmp_path: Path) -> None:
    bars: list[DailyBar] = []
    for n in range(50):
        security = SecurityId(f"SEC-{n:036d}")
        bars.extend(bar(date(2020, 6, day), "100", security_id=security) for day in range(1, 21))
    written = write_prices(bars, tmp_path, source="volume-test")

    assert written == 1000
    assert len(list(tmp_path.rglob("part-*.parquet"))) == 1  # one file, not a thousand
    assert partition_row_counts(tmp_path) == {2020: 1000}
    assert small_partitions(tmp_path) == {2020: 1000}  # below the documented threshold
    assert small_partitions(tmp_path, threshold=100) == {}
    assert SMALL_PARTITION_ROWS > 1000


def test_duckdb_view_prunes_on_the_partition_column(tmp_path: Path) -> None:
    write_prices(
        [bar(date(2019, 6, 1), "100"), bar(date(2020, 6, 1), "110")], tmp_path, source="test"
    )
    con = duckdb_prices(tmp_path)
    rows = con.execute(
        "select trade_date, close from prices_daily where trade_year = 2020"
    ).fetchall()
    assert rows == [(date(2020, 6, 1), Decimal("110.000000"))]

    # DuckDB reports how many of the dataset's files it actually opened; asserting on that
    # is the pruning claim itself rather than an inspection of the output rows.
    plan = con.execute(
        "explain analyze select * from prices_daily where trade_year = 2020"
    ).fetchall()[0][1]
    assert "Scanning Files: 1/2" in plan
    assert "trade_year=2019" not in plan
