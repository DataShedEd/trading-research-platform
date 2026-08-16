"""Revision detection and sequencing: restatements are new rows, never updates.

THE revision key (defined here and nowhere else):

    (security_id, statement, line_item, period_end, period_type)

Currency is deliberately not part of the key — the same fact restated in a different
currency is a data error to investigate (:class:`CurrencyChangeError`), not a revision.

Incoming observations are classified against what is already known for their key:

- **new fact** — no existing rows: stored as revision_sequence 0;
- **unchanged re-observation** — value equals the latest known revision's (exact Decimal
  comparison with exponent normalised, so ``100`` and ``100.00`` are the same fact; the
  stored row keeps its original scale): idempotent no-op, no new row;
- **revision** — value differs from the latest known: appended with the next sequence and
  ``revised_at`` set. Its ``available_at`` is the first-known time of the *restatement* —
  never inherited from the original filing, and required to be strictly later than the
  previous revision's ``available_at`` (:class:`RevisionOrderError`), because a
  restatement made retroactively visible is exactly the leak this module prevents.

Providers that only serve the latest view present restated figures with no trace of the
original. We cannot invent the original; the restated figure simply enters with its own
(possibly DEC-007-imputed) availability, and the provider's revision-visibility limits
are measured by QNT-035 and scored in the bake-off.
"""

from collections import defaultdict
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from datetime import date

from trp.domain.fundamentals import (
    FundamentalValue,
    PeriodType,
    StatementType,
    check_revision_series,
)
from trp.domain.security import revalidated_copy

RevisionKey = tuple[str, StatementType, str, date, PeriodType]


class RevisionError(Exception):
    pass


class CurrencyChangeError(RevisionError):
    pass


class RevisionOrderError(RevisionError):
    pass


@dataclass(frozen=True)
class Classification:
    """Outcome of classifying a batch of observations against existing rows."""

    to_append: tuple[FundamentalValue, ...]
    unchanged: int = 0
    new_facts: int = 0
    revisions: int = 0


def _same_value(a: FundamentalValue, b: FundamentalValue) -> bool:
    # Exact Decimal comparison, exponent-normalised: 100 and 100.00 are one fact.
    return a.value.normalize() == b.value.normalize()


def classify_observations(
    existing: Sequence[FundamentalValue],
    incoming: Iterable[FundamentalValue],
) -> Classification:
    """Classify a batch of incoming observations per revision key.

    ``incoming`` records must arrive as originals (sequence 0, no ``revised_at``) — the
    sequence is assigned here, from what is already known. Returns the rows to append;
    existing rows are never modified (there is no code path that could).
    """
    by_key: dict[RevisionKey, list[FundamentalValue]] = defaultdict(list)
    for record in existing:
        by_key[record.series_key()].append(record)
    for series in by_key.values():
        series.sort(key=lambda r: r.revision_sequence)
        check_revision_series(series)

    to_append: list[FundamentalValue] = []
    unchanged = new_facts = revisions = 0

    for observation in incoming:
        key = observation.series_key()
        series = by_key[key]
        if not series:
            stored = revalidated_copy(observation, revision_sequence=0, revised_at=None)
            by_key[key].append(stored)
            to_append.append(stored)
            new_facts += 1
            continue

        latest = series[-1]
        if latest.currency != observation.currency:
            raise CurrencyChangeError(
                f"{key}: currency changed {latest.currency} -> {observation.currency}; "
                "a currency change is a data error, not a revision"
            )
        if _same_value(latest, observation):
            unchanged += 1
            continue

        if observation.available_at <= latest.available_at:
            raise RevisionOrderError(
                f"{key}: restatement available_at ({observation.available_at}) must be "
                f"strictly after the previous revision's ({latest.available_at})"
            )
        stored = revalidated_copy(
            observation,
            revision_sequence=latest.revision_sequence + 1,
            revised_at=observation.available_at,
        )
        by_key[key].append(stored)
        to_append.append(stored)
        revisions += 1

    return Classification(
        to_append=tuple(to_append),
        unchanged=unchanged,
        new_facts=new_facts,
        revisions=revisions,
    )
