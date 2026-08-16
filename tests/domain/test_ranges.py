from datetime import date

from trp.domain.ranges import contains, first_overlap, ranges_overlap

D = date


def test_half_open_adjacency_does_not_overlap() -> None:
    # Ticker change effective 2015-06-01: old range ends, new begins, same day.
    assert not ranges_overlap(D(2010, 1, 1), D(2015, 6, 1), D(2015, 6, 1), None)


def test_open_ended_ranges_overlap_anything_later() -> None:
    assert ranges_overlap(D(2010, 1, 1), None, D(2020, 1, 1), D(2021, 1, 1))


def test_contains_is_half_open() -> None:
    assert contains(D(2010, 1, 1), D(2015, 6, 1), D(2010, 1, 1))
    assert not contains(D(2010, 1, 1), D(2015, 6, 1), D(2015, 6, 1))
    assert contains(D(2010, 1, 1), None, D(2099, 1, 1))


def test_first_overlap_detects_and_reports_indices() -> None:
    disjoint = [
        (D(2010, 1, 1), D(2012, 1, 1)),
        (D(2012, 1, 1), D(2014, 1, 1)),
        (D(2014, 1, 1), None),
    ]
    assert first_overlap(disjoint) is None

    overlapping = [
        (D(2014, 1, 1), None),
        (D(2010, 1, 1), D(2012, 1, 1)),
        (D(2011, 6, 1), D(2013, 1, 1)),  # overlaps index 1
    ]
    assert first_overlap(overlapping) == (1, 2)


def test_first_overlap_empty_and_single() -> None:
    assert first_overlap([]) is None
    assert first_overlap([(D(2010, 1, 1), None)]) is None
