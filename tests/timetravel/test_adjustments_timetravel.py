"""A dividend the vendor published late must not affect factors computed as at an
earlier knowledge date — late-arriving corporate actions cannot rewrite backtests."""

from datetime import UTC, date, datetime
from decimal import Decimal
from fractions import Fraction

import pytest

from trp.derived.adjustments import compute_adjustment_factors
from trp.domain.corporate_actions import Dividend
from trp.domain.identifiers import new_security_id
from trp.domain.prices import DailyBar

pytestmark = pytest.mark.timetravel

D1, D2 = date(2020, 3, 2), date(2020, 3, 3)
PUBLISHED = datetime(2020, 6, 1, 9, 0, tzinfo=UTC)  # vendor adds the dividend months later
BEFORE = datetime(2020, 4, 1, tzinfo=UTC)
AFTER = datetime(2020, 7, 1, tzinfo=UTC)


def build() -> tuple[list[DailyBar], list[Dividend]]:
    sid = new_security_id()
    ingested = datetime(2020, 3, 4, tzinfo=UTC)
    bars = [
        DailyBar(
            security_id=sid,
            trade_date=trade_date,
            open=close,
            high=close,
            low=close,
            close=close,
            volume=1000,
            currency="GBX",
            source="test",
            ingested_at=ingested,
        )
        for trade_date, close in ((D1, Decimal("200")), (D2, Decimal("190")))
    ]
    dividend = Dividend(
        security_id=sid,
        ex_date=D2,
        source="test",
        available_at=PUBLISHED,
        amount=Decimal("10"),
        currency="GBX",
    )
    return bars, [dividend]


def test_late_published_dividend_invisible_at_earlier_as_of() -> None:
    bars, actions = build()
    sid = bars[0].security_id

    early = compute_adjustment_factors(bars, actions, as_of=BEFORE)
    assert early.exact[(sid, D1)] == (Fraction(1), Fraction(1))
    assert early.provenance.actions_excluded_by_as_of == 1

    late = compute_adjustment_factors(bars, actions, as_of=AFTER)
    assert late.exact[(sid, D1)][1] == Fraction(19, 20)
    assert late.provenance.actions_excluded_by_as_of == 0


def test_naive_as_of_rejected() -> None:
    bars, actions = build()
    with pytest.raises(ValueError, match="timezone-aware"):
        compute_adjustment_factors(bars, actions, as_of=datetime(2020, 4, 1))  # noqa: DTZ001
