"""Half-open effective date ranges.

Every time-varying fact in the security master carries ``valid_from``/``valid_to`` with
half-open semantics ``[valid_from, valid_to)``; ``valid_to=None`` means open-ended. Half-open
ranges make adjacent facts (e.g. a ticker change effective on a given day) representable
without overlap or gap ambiguity.
"""

from collections.abc import Iterable, Sequence
from datetime import date
from itertools import pairwise


def ranges_overlap(a_from: date, a_to: date | None, b_from: date, b_to: date | None) -> bool:
    """True if half-open ranges [a_from, a_to) and [b_from, b_to) intersect."""
    a_ends_before_b = a_to is not None and a_to <= b_from
    b_ends_before_a = b_to is not None and b_to <= a_from
    return not (a_ends_before_b or b_ends_before_a)


def contains(valid_from: date, valid_to: date | None, on: date) -> bool:
    """True if ``on`` falls within the half-open range [valid_from, valid_to)."""
    return valid_from <= on and (valid_to is None or on < valid_to)


def first_overlap(
    ranges: Iterable[tuple[date, date | None]],
) -> tuple[int, int] | None:
    """Return indices of the first overlapping pair, or None if all ranges are disjoint.

    O(n log n); used to enforce the no-overlap invariant on status histories and
    identifier maps.
    """
    indexed: Sequence[tuple[tuple[date, date | None], int]] = sorted(
        ((r, i) for i, r in enumerate(ranges)), key=lambda item: item[0][0]
    )
    for ((_, prev_to), prev_i), ((cur_from, _), cur_i) in pairwise(indexed):
        if prev_to is None or cur_from < prev_to:
            return (prev_i, cur_i)
    return None
