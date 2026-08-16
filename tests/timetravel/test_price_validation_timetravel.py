"""QNT-019 leakage guard: a validation run may only use what was known at `as_of`.

The failure this prevents is subtle and one-directional. A corporate action published in
2021 must not explain away a 2020 move in a run reproducing 2020 — because at the time,
nobody could have known the move was explained, and a check that pretends otherwise
retrospectively certifies data that was in fact unusable. Suppression is the dangerous
direction: a leaked action makes a finding *disappear*, and a finding that disappears is
never adjudicated.
"""

from datetime import UTC, date, datetime
from decimal import Decimal

import pytest

from tests.fixtures.prices import SEC_A, series
from trp.canonical.calendars import get_trading_calendar
from trp.canonical.price_validation import Severity, check_extreme_moves, validate_bars
from trp.canonical.prices import bars_to_frame
from trp.derived.adjustments import compute_adjustment_factors
from trp.domain.corporate_actions import RightsIssue, Split
from trp.domain.prices import DailyBar
from trp.domain.security import Listing

pytestmark = pytest.mark.timetravel

XLON = get_trading_calendar("XLON")
MON, TUE, WED = XLON.sessions_between(date(2020, 3, 2), date(2020, 3, 4))

# The split happened on the Wednesday; the vendor only published it fifteen months later.
PUBLISHED_LATE = datetime(2021, 6, 1, 9, 0, tzinfo=UTC)
REPRODUCING_2020 = datetime(2020, 12, 31, tzinfo=UTC)
TODAY = datetime(2021, 12, 31, tzinfo=UTC)

LISTING = Listing(security_id=SEC_A, mic="XLON", currency="GBX", valid_from=date(2015, 1, 1))


def split_shaped_series() -> list[DailyBar]:
    return series([MON, TUE, WED], ["100", "100", "50"])


LATE_SPLIT = Split(
    security_id=SEC_A,
    ex_date=WED,
    new_shares=2,
    old_shares=1,
    source="test",
    available_at=PUBLISHED_LATE,
)


def test_an_action_published_after_as_of_cannot_explain_a_move() -> None:
    bars = bars_to_frame(split_shaped_series())

    as_of_2020 = check_extreme_moves(bars, [LATE_SPLIT], as_of=REPRODUCING_2020)
    assert len(as_of_2020) == 1
    assert as_of_2020[0].severity is Severity.ERROR
    assert as_of_2020[0].evidence_map["actions_within_window"] == "none"

    # Once the vendor has published it, the same data is explained.
    assert check_extreme_moves(bars, [LATE_SPLIT], as_of=TODAY) == ()


def test_the_whole_report_respects_as_of() -> None:
    bars = split_shaped_series()
    then = validate_bars(bars, as_of=REPRODUCING_2020, actions=[LATE_SPLIT], listings=[LISTING])
    now = validate_bars(bars, as_of=TODAY, actions=[LATE_SPLIT], listings=[LISTING])

    assert then.counts["extreme_move"] == 1
    assert now.counts["extreme_move"] == 0
    assert then.as_of == REPRODUCING_2020


def test_a_rights_issue_warning_is_only_raised_once_the_issue_is_known() -> None:
    """DEC-009's warning is itself point-in-time: the engine can only warn about what it
    has been told. The report must not claim, of a 2020 reproduction, that the adjusted
    series was known to be unreliable when the rights issue was not yet published."""
    rights = RightsIssue(
        security_id=SEC_A,
        ex_date=WED,
        new_shares=1,
        old_shares=1,
        subscription_price=Decimal("10"),
        currency="GBX",
        source="test",
        available_at=PUBLISHED_LATE,
    )
    bars = split_shaped_series()

    then = validate_bars(
        bars,
        as_of=REPRODUCING_2020,
        actions=[rights],
        listings=[LISTING],
        adjustment=compute_adjustment_factors(bars, [rights], as_of=REPRODUCING_2020),
    )
    now = validate_bars(
        bars,
        as_of=TODAY,
        actions=[rights],
        listings=[LISTING],
        adjustment=compute_adjustment_factors(bars, [rights], as_of=TODAY),
    )

    assert then.counts["adjustment_warning"] == 0
    assert now.counts["adjustment_warning"] == 1
