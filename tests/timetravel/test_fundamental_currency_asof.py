"""FX is point-in-time data too: a 2015 conversion may not use a 2016 rate.

The leak this guards is quieter than the fundamentals one. The row itself can be perfectly
knowable at ``as_of`` while the rate needed to express it in the research base currency is
not — the period ends on the 31st, and the 31st's rate is not published until the 31st has
closed. Reaching forward one day for it would look like nothing at all in the output.
"""

from datetime import UTC, date, datetime
from decimal import Decimal
from pathlib import Path

import polars as pl
import pytest

from tests.fakes.fx import FixedRateFx
from trp.canonical.fundamentals.currency import (
    FxRateNotYetAvailableError,
    convert_fundamentals,
    fx_available_at,
)
from trp.canonical.fundamentals.queries import fundamentals
from trp.canonical.fundamentals.storage import write_fundamentals
from trp.domain.fundamentals import FundamentalValue, PeriodType, StatementType
from trp.domain.identifiers import new_security_id

pytestmark = pytest.mark.timetravel

PERIOD_END = date(2019, 12, 31)
RATE_KNOWABLE_FROM = datetime(2020, 1, 1, tzinfo=UTC)


@pytest.fixture
def store(tmp_path: Path) -> tuple[Path, str]:
    """One USD row knowable from the instant its period ends.

    Deliberately extreme — a real filing is months later — because it is the only shape
    that puts the fundamental inside ``as_of`` while the FX rate is still outside it.
    """
    security_id = new_security_id()
    write_fundamentals(
        [
            FundamentalValue(
                security_id=security_id,
                statement=StatementType.BALANCE,
                line_item="total_equity",
                period_end=PERIOD_END,
                period_type=PeriodType.ANNUAL,
                currency="USD",
                value=Decimal("180000000000"),
                available_at=datetime(2019, 12, 31, tzinfo=UTC),
                source="fixture:fx-availability",
            )
        ],
        tmp_path,
        source="fixture:fx-availability",
    )
    return tmp_path, security_id


def query(root: Path, security_id: str, as_of: datetime) -> pl.DataFrame:
    return fundamentals(root, [security_id], ["total_equity"], as_of=as_of)


def test_the_availability_rule_is_the_close_of_the_rate_date() -> None:
    assert fx_available_at(PERIOD_END) == RATE_KNOWABLE_FROM  # err late, per DEC-007's spirit


def test_a_rate_published_after_as_of_is_refused_not_reached_for(
    store: tuple[Path, str],
) -> None:
    root, security_id = store
    as_of = datetime(2019, 12, 31, 12, 0, tzinfo=UTC)
    frame = query(root, security_id, as_of)
    assert frame.height == 1  # the fundamental itself is legitimately knowable

    fx = FixedRateFx({("USD", "GBP"): Decimal("0.8")})
    with pytest.raises(FxRateNotYetAvailableError) as raised:
        convert_fundamentals(frame, to_currency="GBP", fx=fx, as_of=as_of)

    assert raised.value.on == PERIOD_END
    assert raised.value.available_at == RATE_KNOWABLE_FROM
    assert fx.calls == []  # the provider was never even asked


def test_the_leak_guard_does_not_soften_in_non_strict_mode(store: tuple[Path, str]) -> None:
    """``strict`` decides what missing data does. It never licenses look-ahead."""
    root, security_id = store
    as_of = datetime(2019, 12, 31, 12, 0, tzinfo=UTC)
    with pytest.raises(FxRateNotYetAvailableError):
        convert_fundamentals(
            query(root, security_id, as_of),
            to_currency="GBP",
            fx=FixedRateFx({("USD", "GBP"): Decimal("0.8")}),
            as_of=as_of,
            strict=False,
        )


def test_once_the_rate_is_knowable_the_conversion_uses_that_dates_rate(
    store: tuple[Path, str],
) -> None:
    root, security_id = store
    fx = FixedRateFx({("USD", "GBP"): Decimal("0.8")})
    frame = convert_fundamentals(
        query(root, security_id, RATE_KNOWABLE_FROM),
        to_currency="GBP",
        fx=fx,
        as_of=RATE_KNOWABLE_FROM,
    )
    row = frame.to_dicts()[0]
    assert row["converted_value"] == Decimal("144000000000")
    assert row["fx_rate_date"] == PERIOD_END
    assert row["fx_rate_available_at"] == RATE_KNOWABLE_FROM

    # No rate was ever requested for a date the query could not know about.
    assert fx.calls == [("USD", "GBP", PERIOD_END)]
    assert all(fx_available_at(on) <= RATE_KNOWABLE_FROM for _, _, on in fx.calls)
