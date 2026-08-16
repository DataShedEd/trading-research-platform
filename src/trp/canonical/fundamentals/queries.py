"""THE point-in-time fundamentals query — the only supported read path for research.

`fundamentals(...)` returns, per (security, statement, line item, period), exactly one
row: the highest revision whose ``available_at <= as_of``. Periods with nothing knowable
at ``as_of`` are omitted, never filled.

The trap this module exists to avoid: filtering on ``period_end <= as_of`` looks
equivalent and is not — a December 2017 annual result is not knowable in January 2018.
Only ``available_at`` is load-bearing; ``filed_at`` is frequently absent and
``period_end`` is an event date, not a knowledge date. The ``as_of`` predicate is applied
in exactly one place (:func:`_apply_as_of`) that every query path goes through; there is
no public unfiltered read here, and research code must not read the Parquet files
directly (see CLAUDE.md).

Semantics at the edges (documented + tested): an ``as_of`` earlier than everything known
returns an **empty** frame (a legitimate answer: nothing was knowable); a requested line
item that exists nowhere in the dataset **raises** (a likely typo — silence would read as
"no data").
"""

from collections.abc import Sequence
from datetime import date, datetime
from pathlib import Path

import polars as pl

from trp.canonical.fundamentals.storage import known_line_items, read_fundamentals
from trp.domain.fundamentals import PeriodType, StatementType

_KEY = ["security_id", "statement", "line_item", "period_end", "period_type"]


class UnknownLineItemError(Exception):
    def __init__(self, unknown: set[str]) -> None:
        super().__init__(
            f"line item(s) {sorted(unknown)} do not exist anywhere in the dataset — "
            "likely a typo; an empty result would be misleading"
        )


def _apply_as_of(frame: pl.DataFrame, as_of: datetime) -> pl.DataFrame:
    """The single choke point for the point-in-time predicate."""
    if as_of.tzinfo is None:
        raise ValueError("as_of must be timezone-aware (UTC)")
    return frame.filter(pl.col("available_at") <= as_of)


def fundamentals(
    root: Path,
    security_ids: Sequence[str],
    line_items: Sequence[str],
    *,
    as_of: datetime,
    statement: StatementType | None = None,
    period_type: PeriodType | None = None,
    period_start: date | None = None,
    period_end: date | None = None,
) -> pl.DataFrame:
    """Latest-known fundamental values as at ``as_of``.

    Returns one row per (security, statement, line item, period) with full provenance:
    ``available_at``, ``revision_sequence``, ``availability_imputed``, ``currency`` and
    ``source`` — auditable without a second query.
    """
    known_items = known_line_items(root)
    unknown = set(line_items) - known_items
    if unknown and known_items:
        raise UnknownLineItemError(unknown)

    frame = read_fundamentals(
        root,
        security_ids=list(security_ids),
        line_items=list(line_items),
        period_start=period_start,
        period_end=period_end,
    )
    if statement is not None:
        frame = frame.filter(pl.col("statement") == statement.value)
    if period_type is not None:
        frame = frame.filter(pl.col("period_type") == period_type.value)

    knowable = _apply_as_of(frame, as_of)
    if knowable.is_empty():
        return knowable
    return knowable.sort("revision_sequence").group_by(_KEY, maintain_order=True).last().sort(_KEY)
