"""Partitioned Parquet persistence for canonical daily bars.

Layout: ``<root>/trade_year=YYYY/part-<n>.parquet``, mirroring the fundamentals dataset
(DEC-011). Partitioning by trade-date year only: the dominant research query is a date
range across the whole universe, so pruning by date is what pays, while partitioning by
security would produce one tiny file per security per year — the file-count explosion the
fundamentals decision already rejected. A universe-year of daily bars for a few thousand
securities is a few hundred thousand rows: one comfortable file.

Rows within a partition are sorted by ``security_id`` then ``trade_date`` so that
row-group statistics let a reader skip within a file as well as between partitions.

Append-only. Each write lands new ``part-<n>`` files; existing files are NEVER rewritten.
Re-ingestion is made idempotent by an anti-join on the stable row key
``(security_id, trade_date, source)`` rather than by rewriting the partitions a load
touches: rewriting is the mechanism QNT-018 originally proposed, but it makes a bad
ingestion destructive of good rows in the same year, and the same key that makes the
anti-join correct also makes two providers' views of the same bar coexist rather than
overwrite each other (which the bake-off needs). Compaction of the resulting part files is
therefore a deliberate future operation, never implicit — see :func:`small_partitions`.

Value type: the pinned ``PRICES_DAILY_SCHEMA`` from QNT-013 — Parquet ``Decimal(18, 6)``
for prices, ``Int64`` for whole-share volume, UTC ``ingested_at``. No float64 (DEC-005),
and no schema inference: a provider file whose columns disagree fails the write.

Point-in-time: :func:`read_prices` takes an optional ``as_of`` bounding ``ingested_at``,
so a reproduction of an earlier state cannot see bars ingested after it — a re-ingestion of
revised history does not silently change an old result.

Single-writer model per DEC-003 — atomicity is staged-write-then-rename, no locking. Every
write appends one JSON line to ``_ingestion_log.jsonl`` (run label, row counts, files,
timestamp) so "when did this bar arrive?" is always answerable (QUANT_PRINCIPLES §4).

This is the storage layer, not the research API: it returns frames and bars, and applies no
adjustment. Adjusted prices are derived (QNT-015).
"""

import json
from collections.abc import Sequence
from datetime import UTC, date, datetime
from pathlib import Path

import duckdb
import polars as pl

from trp.canonical.prices import PRICES_DAILY_SCHEMA, bars_to_frame, frame_to_bars
from trp.domain.prices import DailyBar

# The stable identity of a bar. `source` is part of the key deliberately: the same
# security-day from two providers is two rows to be compared, not a collision to resolve
# here (provider reconciliation is the bake-off's job, not storage's).
PRICE_ROW_KEY = ("security_id", "trade_date", "source")

_SORT_KEY = ("security_id", "trade_date", "source")

_PARTITION_PREFIX = "trade_year="

# A partition holding fewer rows than this is a candidate for compaction, not an error:
# it means a year was loaded incrementally (a daily run writes one small file per day)
# rather than backfilled in one pass. Roughly a universe-week of bars.
SMALL_PARTITION_ROWS = 10_000


class PriceStorageError(Exception):
    pass


def _partition_directory(root: Path, year: int) -> Path:
    return root / f"{_PARTITION_PREFIX}{year}"


def _partition_year(directory: Path) -> int:
    return int(directory.name.removeprefix(_PARTITION_PREFIX))


def partition_files(
    root: Path, *, start: date | None = None, end: date | None = None
) -> list[Path]:
    """Part files whose partition can hold a bar in ``[start, end]`` — the pruning step.

    Exposed because a reader that does its own scanning still has to prune the same way.
    """
    if not root.exists():
        return []
    files: list[Path] = []
    for directory in sorted(root.glob(f"{_PARTITION_PREFIX}*")):
        year = _partition_year(directory)
        if start is not None and year < start.year:
            continue
        if end is not None and year > end.year:
            continue
        files.extend(sorted(directory.glob("part-*.parquet")))
    return files


def _existing_keys(root: Path, years: Sequence[int]) -> pl.DataFrame | None:
    """Keys already stored in the partitions the incoming rows would land in.

    Only those partitions are read: a re-ingestion of one year must not scan twenty.
    """
    files: list[Path] = []
    for year in sorted(set(years)):
        files.extend(sorted(_partition_directory(root, year).glob("part-*.parquet")))
    if not files:
        return None
    return pl.concat([pl.read_parquet(f, columns=list(PRICE_ROW_KEY)) for f in files])


def write_prices(bars: Sequence[DailyBar], root: Path, *, source: str) -> int:
    """Append genuinely new bars; returns how many rows were written.

    ``source`` labels the ingestion run in the log and is independent of each bar's own
    ``source`` field, which identifies the provider the values came from.

    Bars whose ``(security_id, trade_date, source)`` is already stored are skipped, so a
    re-run over identical input writes nothing and cannot duplicate a bar — a duplicated
    bar silently doubles a day's weight in every aggregate. Existing files are never
    modified. Staged-then-renamed per partition, so an interrupted write leaves the
    dataset exactly as it was.
    """
    if not bars:
        return 0
    incoming = bars_to_frame(list(bars))
    years = incoming.get_column("trade_date").dt.year().unique().to_list()
    existing = _existing_keys(root, years)
    if existing is not None:
        incoming = incoming.join(existing, on=list(PRICE_ROW_KEY), how="anti")
    if incoming.is_empty():
        _log(root, source=source, rows_written=0, files=[])
        return 0
    incoming = incoming.sort(list(_SORT_KEY))

    staged: list[tuple[Path, Path]] = []
    written: list[str] = []
    try:
        for (year,), partition in incoming.group_by(
            pl.col("trade_date").dt.year(), maintain_order=True
        ):
            directory = _partition_directory(root, int(year))
            directory.mkdir(parents=True, exist_ok=True)
            sequence = len(list(directory.glob("part-*.parquet")))
            final = directory / f"part-{sequence:05d}.parquet"
            if final.exists():  # never rewrite
                raise PriceStorageError(f"refusing to overwrite {final}")
            tmp = directory / f".part-{sequence:05d}.parquet.tmp"
            partition.write_parquet(tmp)
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


def read_prices(
    root: Path,
    *,
    security_ids: Sequence[str] | None = None,
    start: date | None = None,
    end: date | None = None,
    sources: Sequence[str] | None = None,
    as_of: datetime | None = None,
) -> pl.DataFrame:
    """Load a subset of the dataset; year partitions outside ``[start, end]`` are not read.

    ``as_of`` (UTC) bounds ``ingested_at``: bars that arrived later are invisible, which is
    what makes an earlier reproduction stable across re-ingestions.
    """
    if as_of is not None and as_of.tzinfo is None:
        raise ValueError("as_of must be timezone-aware (UTC)")
    files = partition_files(root, start=start, end=end)
    if not files:
        return pl.DataFrame(schema=PRICES_DAILY_SCHEMA)
    frame = pl.concat([pl.read_parquet(f) for f in files])
    if security_ids is not None:
        frame = frame.filter(pl.col("security_id").is_in(list(security_ids)))
    if sources is not None:
        frame = frame.filter(pl.col("source").is_in(list(sources)))
    if start is not None:
        frame = frame.filter(pl.col("trade_date") >= start)
    if end is not None:
        frame = frame.filter(pl.col("trade_date") <= end)
    if as_of is not None:
        frame = frame.filter(pl.col("ingested_at") <= as_of)
    return frame.sort(list(_SORT_KEY))


def read_bars(
    root: Path,
    *,
    security_ids: Sequence[str] | None = None,
    start: date | None = None,
    end: date | None = None,
    sources: Sequence[str] | None = None,
    as_of: datetime | None = None,
) -> list[DailyBar]:
    """:func:`read_prices` reconstructed into domain models, re-running every invariant."""
    return frame_to_bars(
        read_prices(
            root,
            security_ids=security_ids,
            start=start,
            end=end,
            sources=sources,
            as_of=as_of,
        )
    )


def partition_row_counts(root: Path) -> dict[int, int]:
    """Rows per trade-year partition — the measurement behind any compaction decision."""
    counts: dict[int, int] = {}
    if not root.exists():
        return counts
    for directory in sorted(root.glob(f"{_PARTITION_PREFIX}*")):
        files = sorted(directory.glob("part-*.parquet"))
        if not files:
            continue
        counts[_partition_year(directory)] = sum(
            pl.read_parquet(f, columns=["trade_date"]).height for f in files
        )
    return counts


def small_partitions(root: Path, *, threshold: int = SMALL_PARTITION_ROWS) -> dict[int, int]:
    """Partitions below the documented row threshold. Reported, never compacted here."""
    return {year: rows for year, rows in partition_row_counts(root).items() if rows < threshold}


def duckdb_prices(root: Path) -> duckdb.DuckDBPyConnection:
    """A connection with the dataset registered as a ``prices_daily`` view.

    The Hive-style directory name is exposed as a ``trade_year`` column, so a query with a
    ``trade_year`` predicate prunes partitions in DuckDB exactly as :func:`read_prices`
    does in Python::

        con.execute(
            "select * from prices_daily where trade_year = 2020 and security_id = ?",
            [security_id],
        )
    """
    con = duckdb.connect()
    # CREATE VIEW cannot be a prepared statement; escape the path literal instead.
    pattern = str(root / f"{_PARTITION_PREFIX}*" / "part-*.parquet").replace("'", "''")
    con.execute(
        "create view prices_daily as "
        f"select * from read_parquet('{pattern}', hive_partitioning = true)"
    )
    return con


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
