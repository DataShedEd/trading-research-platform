"""Parquet persistence for canonical fundamentals.

Layout (DEC-011): ``data/canonical/fundamentals/period_year=YYYY/part-<n>.parquet``.
Partitioning by period-end year only: the dominant query touches a few line items across
many securities filtered by ``available_at``, so security-level partitioning would
explode the file count while year-level keeps whole-universe files modest (one universe-
year of annual+interim statements is tens of thousands of rows — one comfortable file)
and lets period-range queries prune. Each write appends new ``part-<n>`` files; existing
files are NEVER rewritten (the storage half of QNT-022's append-only rule).

Value type (DEC-011): Parquet ``Decimal(38, 6)`` — six decimal places for per-share
pence, thirty-two integer digits for trillion-scale balance-sheet lines. Out-of-range
values error; nothing is truncated. No float64 anywhere (DEC-005).

Idempotence: the stable row key is (revision key, revision_sequence). Rows already
present are skipped; only genuinely new rows are written, into new files. Single-writer
model per DEC-003 — atomicity is staged-write-then-rename, no locking.

Every write appends one JSON line to ``_ingestion_log.jsonl`` (source, row counts,
files written, timestamp) so "when did this row arrive?" is always answerable
(QUANT_PRINCIPLES §4).
"""

import json
from collections.abc import Sequence
from datetime import UTC, date, datetime
from pathlib import Path

import polars as pl

from trp.domain.fundamentals import FundamentalValue

VALUE_DECIMAL = pl.Decimal(precision=38, scale=6)

FUNDAMENTALS_SCHEMA: dict[str, pl.DataType | type[pl.DataType]] = {
    "security_id": pl.Utf8,
    "statement": pl.Utf8,
    "line_item": pl.Utf8,
    "period_end": pl.Date,
    "period_type": pl.Utf8,
    "currency": pl.Utf8,
    "value": VALUE_DECIMAL,
    "filed_at": pl.Datetime(time_unit="us", time_zone="UTC"),
    "available_at": pl.Datetime(time_unit="us", time_zone="UTC"),
    "revised_at": pl.Datetime(time_unit="us", time_zone="UTC"),
    "revision_sequence": pl.Int32,
    "source": pl.Utf8,
    "availability_imputed": pl.Boolean,
    "imputation_rule": pl.Utf8,
}

_ROW_KEY = [
    "security_id",
    "statement",
    "line_item",
    "period_end",
    "period_type",
    "revision_sequence",
]


class FundamentalStorageError(Exception):
    pass


def _frame(records: Sequence[FundamentalValue]) -> pl.DataFrame:
    rows = [r.model_dump(mode="python") for r in records]
    return pl.DataFrame(rows, schema=FUNDAMENTALS_SCHEMA).sort(_ROW_KEY)


def write_fundamentals(records: Sequence[FundamentalValue], root: Path, *, source: str) -> int:
    """Append genuinely new rows; returns how many were written.

    Existing rows are never modified or rewritten; a re-run over identical records writes
    nothing. Staged-then-renamed per partition, so an interrupted write leaves the
    dataset exactly as it was.
    """
    if not records:
        return 0
    incoming = _frame(records)
    existing_keys = _existing_keys(root)
    if existing_keys is not None:
        incoming = incoming.join(existing_keys, on=_ROW_KEY, how="anti")
    if incoming.is_empty():
        _log(root, source=source, rows_written=0, files=[])
        return 0

    staged: list[tuple[Path, Path]] = []
    written: list[str] = []
    try:
        for (year,), partition in incoming.group_by(
            pl.col("period_end").dt.year(), maintain_order=True
        ):
            directory = root / f"period_year={year}"
            directory.mkdir(parents=True, exist_ok=True)
            sequence = len(list(directory.glob("part-*.parquet")))
            final = directory / f"part-{sequence:05d}.parquet"
            if final.exists():  # never rewrite
                raise FundamentalStorageError(f"refusing to overwrite {final}")
            tmp = directory / f".part-{sequence:05d}.parquet.tmp"
            partition.drop("period_end_year", strict=False).write_parquet(tmp)
            staged.append((tmp, final))
            written.append(str(final.relative_to(root)))
    except BaseException:
        for tmp, _ in staged:
            tmp.unlink(missing_ok=True)
        raise
    for tmp, final in staged:
        tmp.replace(final)
    _log(root, source=source, rows_written=int(incoming.height), files=written)
    return int(incoming.height)


def _existing_keys(root: Path) -> pl.DataFrame | None:
    files = _partition_files(root)
    if not files:
        return None
    return pl.concat([pl.read_parquet(f, columns=_ROW_KEY) for f in files])


def _partition_files(
    root: Path, *, period_start: date | None = None, period_end: date | None = None
) -> list[Path]:
    if not root.exists():
        return []
    files: list[Path] = []
    for directory in sorted(root.glob("period_year=*")):
        year = int(directory.name.split("=")[1])
        if period_start is not None and year < period_start.year:
            continue
        if period_end is not None and year > period_end.year:
            continue
        files.extend(sorted(directory.glob("part-*.parquet")))
    return files


def read_fundamentals(
    root: Path,
    *,
    security_ids: Sequence[str] | None = None,
    line_items: Sequence[str] | None = None,
    period_start: date | None = None,
    period_end: date | None = None,
) -> pl.DataFrame:
    """Load a subset without scanning the whole dataset (year partitions prune).

    This is the storage layer, not the research API: research code must go through the
    as-of query module (QNT-025), never read these files directly.
    """
    files = _partition_files(root, period_start=period_start, period_end=period_end)
    if not files:
        return pl.DataFrame(schema=FUNDAMENTALS_SCHEMA)
    frame = pl.concat([pl.read_parquet(f) for f in files])
    if security_ids is not None:
        frame = frame.filter(pl.col("security_id").is_in(list(security_ids)))
    if line_items is not None:
        frame = frame.filter(pl.col("line_item").is_in(list(line_items)))
    if period_start is not None:
        frame = frame.filter(pl.col("period_end") >= period_start)
    if period_end is not None:
        frame = frame.filter(pl.col("period_end") <= period_end)
    return frame.sort(_ROW_KEY)


def known_line_items(root: Path) -> set[str]:
    """Distinct line items across the dataset (columnar read: line_item only)."""
    files = _partition_files(root)
    if not files:
        return set()
    frame = pl.concat([pl.read_parquet(f, columns=["line_item"]) for f in files])
    return set(frame.get_column("line_item").unique().to_list())


def _log(root: Path, *, source: str, rows_written: int, files: list[str]) -> None:
    root.mkdir(parents=True, exist_ok=True)
    entry = {
        "written_at": datetime.now(UTC).isoformat(),
        "source": source,
        "rows_written": rows_written,
        "files": files,
    }
    with (root / "_ingestion_log.jsonl").open("a") as log:
        log.write(json.dumps(entry) + "\n")
