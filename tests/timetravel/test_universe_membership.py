"""Universe survivorship and knowledge-time guarantees (QNT-037/038)."""

from datetime import UTC, date, datetime
from pathlib import Path

import pytest

from tests.universe.conftest import BACKFILL_RECORDED, build_ftse100
from trp.domain.identifiers import SecurityId
from trp.domain.ranges import contains
from trp.universe.membership import visible_as_of
from trp.universe.query import UniverseQuery
from trp.universe.storage import read_universe, write_universe

pytestmark = pytest.mark.timetravel


@pytest.fixture
def stored_ftse100(tmp_path: Path) -> tuple[Path, dict[str, SecurityId]]:
    records, ids = build_ftse100()
    write_universe(records, tmp_path, known_security_ids=set(ids.values()))
    return tmp_path, ids


def test_storage_layer_cannot_leak_future_membership(
    stored_ftse100: tuple[Path, dict[str, SecurityId]],
) -> None:
    # Established at the storage layer, not only in the query API: reconstruct 2019
    # directly from stored records — the 2020 joiner must be absent.
    root, ids = stored_ftse100
    records = read_universe(root, "FTSE100")
    on = date(2019, 8, 1)
    members_2019 = {
        r.security_id
        for r in visible_as_of(records, None)
        if contains(r.valid_from, r.valid_to, on)
    }
    assert ids["backfilled"] not in members_2019
    assert ids["current"] in members_2019


def test_backfilled_row_invisible_to_earlier_knowledge(
    stored_ftse100: tuple[Path, dict[str, SecurityId]],
) -> None:
    root, ids = stored_ftse100
    query = UniverseQuery(root)
    on = date(2020, 6, 1)  # the backfilled spell HAS started by now (event time)

    # With all current knowledge: the joiner is a member.
    assert ids["backfilled"] in query.members("FTSE100", on)
    # But at a knowledge time before the vendor backfilled the row (2021-01-15),
    # our database genuinely did not contain it.
    before_backfill = datetime(2020, 7, 1, tzinfo=UTC)
    assert ids["backfilled"] not in query.members("FTSE100", on, as_of=before_backfill)
    after_backfill = BACKFILL_RECORDED
    assert ids["backfilled"] in query.members("FTSE100", on, as_of=after_backfill)


def test_current_constituents_absent_before_their_spell(
    stored_ftse100: tuple[Path, dict[str, SecurityId]],
) -> None:
    root, ids = stored_ftse100
    query = UniverseQuery(root)
    # A query would "fall back to current membership" if it ignored event time; the
    # re-entrant's second (current) spell must not make it a member in 2016.
    assert ids["reentrant"] not in query.members("FTSE100", date(2016, 6, 1))
