"""Point-in-time fundamental values — the easiest place to leak the future, made hard.

The load-bearing distinction:

- ``filed_at`` — what the provider *claims* about publication. Informational.
- ``available_at`` — our conservative answer to "from when was a researcher entitled to
  know this?" **Required, never None.** Every as-of query filters on it (QNT-025) and must
  never fall back to ``filed_at`` or ``period_end``.

Where no announcement timestamp exists, DEC-007 applies: impute late (period end plus a
documented per-market lag), set ``availability_imputed`` and name the rule applied
(``imputation_rule``, e.g. ``"uk-annual-lag-90d"``) so QNT-035 can measure how wrong the
assumption was. The lag table itself lives with ingestion, not in this model.

``available_at < period_end`` is rejected: providers do emit such rows (pre-announcements,
mislabelled periods) and they are data errors to investigate, never quietly corrected.
The reverse relation is asserted here and ONLY here — downstream code must still filter on
``available_at`` and never reason "the period end is in the past, so it must be known".

Subject: fundamentals attach to a ``security_id`` (consistent with the rest of the
platform); entity-level analysis goes through the security master's entity link.

Revisions are new rows, never updates: ``revision_sequence`` 0 is the original filing;
restatements carry increasing sequences and ``revised_at``. Series-level rules
(contiguity, monotonic timestamps) are checked by :func:`check_revision_series`, reused by
the revision-storage layer (QNT-022).
"""

from collections.abc import Sequence
from datetime import UTC, date, datetime, time, timedelta
from decimal import Decimal
from enum import StrEnum
from itertools import pairwise
from typing import Self

from pydantic import Field, model_validator

from trp.domain.identifiers import SecurityId
from trp.domain.security import FrozenModel


class StatementType(StrEnum):
    INCOME = "income"
    BALANCE = "balance"
    CASH_FLOW = "cash_flow"


class PeriodType(StrEnum):
    ANNUAL = "annual"
    INTERIM = "interim"
    QUARTERLY = "quarterly"


def conservative_available_at(period_end: date, lag: timedelta) -> datetime:
    """DEC-007 imputation: start of the period-end day (UTC) plus a documented lag."""
    return datetime.combine(period_end, time.min, tzinfo=UTC) + lag


class FundamentalValue(FrozenModel):
    security_id: SecurityId
    statement: StatementType
    line_item: str = Field(min_length=1, description="canonical name; taxonomy is QNT-021")
    period_end: date
    period_type: PeriodType
    currency: str = Field(pattern=r"^[A-Z]{3}$", description="reporting currency, ISO 4217")
    value: Decimal = Field(strict=True, description="strict: float input is rejected, not coerced")
    filed_at: datetime | None = None
    available_at: datetime
    revised_at: datetime | None = None
    revision_sequence: int = Field(default=0, ge=0)
    source: str = Field(min_length=1)
    availability_imputed: bool = False
    imputation_rule: str | None = None

    @model_validator(mode="after")
    def _pit_invariants(self) -> Self:
        for label, stamp in (
            ("available_at", self.available_at),
            ("filed_at", self.filed_at),
            ("revised_at", self.revised_at),
        ):
            if stamp is not None and stamp.tzinfo is None:
                raise ValueError(f"{label} must be timezone-aware (UTC)")

        period_end_instant = datetime.combine(self.period_end, time.min, tzinfo=UTC)
        if self.available_at < period_end_instant:
            raise ValueError(
                f"available_at ({self.available_at}) precedes period_end "
                f"({self.period_end}): a data error to investigate, not to correct"
            )

        if self.revision_sequence > 0 and self.revised_at is None:
            raise ValueError("a revision (sequence > 0) must carry revised_at")
        if self.revision_sequence == 0 and self.revised_at is not None:
            raise ValueError("the original filing (sequence 0) must not carry revised_at")

        if self.availability_imputed != (self.imputation_rule is not None):
            raise ValueError(
                "availability_imputed must be set exactly when imputation_rule names the rule"
            )
        return self

    def series_key(self) -> tuple[str, StatementType, str, date, PeriodType]:
        return (self.security_id, self.statement, self.line_item, self.period_end, self.period_type)


class RevisionSeriesError(Exception):
    pass


def check_revision_series(records: Sequence[FundamentalValue]) -> None:
    """Validate a revision series for one (security, statement, line item, period) key:
    sequences 0..n contiguous with no duplicates, and revision timestamps strictly
    increasing. Raises :class:`RevisionSeriesError` naming the violation."""
    if not records:
        return
    keys = {r.series_key() for r in records}
    if len(keys) > 1:
        raise RevisionSeriesError(f"records span {len(keys)} distinct series keys: {sorted(keys)}")

    ordered = sorted(records, key=lambda r: r.revision_sequence)
    sequences = [r.revision_sequence for r in ordered]
    if sequences != list(range(len(ordered))):
        raise RevisionSeriesError(
            f"revision sequences must be contiguous from 0; got {sequences}"
        )
    stamps = [r.revised_at for r in ordered[1:]]
    for earlier, later in pairwise(stamps):
        assert earlier is not None and later is not None  # guaranteed by the record validator
        if later <= earlier:
            raise RevisionSeriesError(
                f"revised_at must strictly increase across revisions; {later} follows {earlier}"
            )
