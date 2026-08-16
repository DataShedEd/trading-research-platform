from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path

import pytest

from tests.fixtures.fundamentals import fundamental, tesco_restatement
from trp.canonical.fundamentals.queries import UnknownLineItemError, fundamentals
from trp.canonical.fundamentals.storage import write_fundamentals

LATEST = datetime(2026, 1, 1, tzinfo=UTC)


@pytest.fixture
def store(tmp_path: Path) -> tuple[Path, str]:
    original, restated = tesco_restatement()
    write_fundamentals([original, restated], tmp_path, source="fixture")
    return tmp_path, original.security_id


def test_returns_one_row_per_key_with_provenance(store: tuple[Path, str]) -> None:
    root, sid = store
    frame = fundamentals(root, [sid], ["trading_profit_guidance"], as_of=LATEST)
    assert frame.height == 1
    row = frame.to_dicts()[0]
    assert row["value"] == Decimal("850000000")
    for column in (
        "available_at",
        "revision_sequence",
        "availability_imputed",
        "currency",
        "source",
    ):
        assert column in row  # auditable without a second query
    assert row["revision_sequence"] == 1


def test_as_of_is_required_keyword_and_aware(store: tuple[Path, str]) -> None:
    root, sid = store
    with pytest.raises(TypeError):
        fundamentals(root, [sid], ["trading_profit_guidance"])  # type: ignore[call-arg]
    with pytest.raises(ValueError, match="timezone-aware"):
        fundamentals(root, [sid], ["trading_profit_guidance"], as_of=datetime(2020, 1, 1))  # noqa: DTZ001


def test_early_as_of_is_empty_but_unknown_line_item_raises(store: tuple[Path, str]) -> None:
    root, sid = store
    early = fundamentals(
        root, [sid], ["trading_profit_guidance"], as_of=datetime(2000, 1, 1, tzinfo=UTC)
    )
    assert early.is_empty()  # nothing was knowable: a legitimate empty answer

    with pytest.raises(UnknownLineItemError, match="revnue"):
        fundamentals(root, [sid], ["revnue"], as_of=LATEST)  # typo must be loud


def test_unrequested_securities_are_absent(store: tuple[Path, str]) -> None:
    root, sid = store
    other = fundamental()  # different security, different line item
    write_fundamentals([other], root, source="fixture-2")
    frame = fundamentals(root, [sid], ["trading_profit_guidance"], as_of=LATEST)
    assert set(frame.get_column("security_id").to_list()) == {sid}
