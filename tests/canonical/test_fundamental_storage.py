from datetime import UTC, date, datetime
from decimal import Decimal
from pathlib import Path

import polars as pl
import pytest

from tests.fixtures.fundamentals import fundamental
from trp.canonical.fundamentals.storage import read_fundamentals, write_fundamentals
from trp.domain.fundamentals import FundamentalValue
from trp.domain.identifiers import new_security_id
from trp.domain.security import revalidated_copy


def files_snapshot(root: Path) -> dict[str, bytes]:
    return {str(p.relative_to(root)): p.read_bytes() for p in root.rglob("part-*.parquet")}


def test_round_trip_preserves_decimals_and_temporal_types(tmp_path: Path) -> None:
    huge = fundamental(value=Decimal("987654321012345.5"), line_item="total_assets")
    tiny = revalidated_copy(huge, line_item="eps", value=Decimal("0.000125"))
    write_fundamentals([huge, tiny], tmp_path, source="test")

    frame = read_fundamentals(tmp_path)
    values = {row["line_item"]: row["value"] for row in frame.to_dicts()}
    assert isinstance(values["total_assets"], Decimal)
    assert values["total_assets"] == Decimal("987654321012345.5")
    assert values["eps"] == Decimal("0.000125")

    row = frame.to_dicts()[0]
    assert row["available_at"].tzinfo is not None
    assert isinstance(row["period_end"], date)
    assert not isinstance(row["period_end"], datetime)


def test_reingesting_identical_rows_is_a_no_op(tmp_path: Path) -> None:
    records = [fundamental(), fundamental(line_item="operating_profit")]
    assert write_fundamentals(records, tmp_path, source="run-1") == 2
    before = files_snapshot(tmp_path)

    assert write_fundamentals(records, tmp_path, source="run-2") == 0
    assert files_snapshot(tmp_path) == before  # nothing rewritten, nothing added


def test_one_new_revision_appends_one_row_leaving_history_byte_identical(
    tmp_path: Path,
) -> None:
    original = fundamental()
    write_fundamentals([original], tmp_path, source="run-1")
    before = files_snapshot(tmp_path)

    revision = revalidated_copy(
        original,
        value=Decimal("1"),
        revision_sequence=1,
        available_at=datetime(2020, 9, 1, tzinfo=UTC),
        revised_at=datetime(2020, 9, 1, tzinfo=UTC),
    )
    assert write_fundamentals([original, revision], tmp_path, source="run-2") == 1
    after = files_snapshot(tmp_path)
    for name, content in before.items():
        assert after[name] == content
    assert read_fundamentals(tmp_path).height == 2


def test_interrupted_write_leaves_dataset_unchanged(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    write_fundamentals([fundamental()], tmp_path, source="run-1")
    before = files_snapshot(tmp_path)

    def explode(self: pl.DataFrame, *args: object, **kwargs: object) -> None:
        raise OSError("disk full")

    monkeypatch.setattr(pl.DataFrame, "write_parquet", explode)
    with pytest.raises(OSError, match="disk full"):
        write_fundamentals([fundamental(line_item="new_item")], tmp_path, source="run-2")
    monkeypatch.undo()
    assert files_snapshot(tmp_path) == before
    assert list(tmp_path.rglob("*.tmp")) == []


def test_partition_pruning_reads_only_matching_years(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    by_year = [
        fundamental(
            period_end=date(year, 12, 31),
            available_at=datetime(year + 1, 3, 1, tzinfo=UTC),
            filed_at=None,
        )
        for year in (2018, 2019, 2020)
    ]
    write_fundamentals(by_year, tmp_path, source="test")
    assert {p.name for p in tmp_path.glob("period_year=*")} == {
        "period_year=2018",
        "period_year=2019",
        "period_year=2020",
    }

    touched: list[str] = []
    original_read = pl.read_parquet

    def spy(source: object, *args: object, **kwargs: object) -> pl.DataFrame:
        touched.append(str(source))
        return original_read(source, *args, **kwargs)  # type: ignore[arg-type]

    monkeypatch.setattr(pl, "read_parquet", spy)
    frame = read_fundamentals(
        tmp_path, period_start=date(2019, 1, 1), period_end=date(2019, 12, 31)
    )
    assert frame.height == 1
    assert all("period_year=2019" in path for path in touched)


def test_ingestion_log_records_every_write(tmp_path: Path) -> None:
    write_fundamentals([fundamental()], tmp_path, source="backfill-2026-08")
    log = (tmp_path / "_ingestion_log.jsonl").read_text().strip().splitlines()
    assert len(log) == 1
    assert '"source": "backfill-2026-08"' in log[0]
    assert '"rows_written": 1' in log[0]


def test_synthetic_volume_produces_sane_file_counts(tmp_path: Path) -> None:
    # ~3000 rows across 3 period-years in one ingestion: one file per partition, not
    # thousands of tiny files.
    records: list[FundamentalValue] = []
    for year in (2018, 2019, 2020):
        for n in range(100):
            sid = new_security_id()
            for item in ("revenue", "operating_profit", "total_assets"):
                records.append(
                    fundamental(
                        security_id=sid,
                        line_item=item,
                        period_end=date(year, 12, 31),
                        available_at=datetime(year + 1, 3, 1, tzinfo=UTC),
                        filed_at=None,
                        value=Decimal(n),
                    )
                )
    written = write_fundamentals(records, tmp_path, source="volume-test")
    assert written == 900
    parquet_files = list(tmp_path.rglob("part-*.parquet"))
    assert len(parquet_files) == 3  # one per period-year partition
