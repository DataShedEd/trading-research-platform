"""Shared fixture universe: a delisted member, a two-spell re-entrant, an open-ended
current member, and a late-backfilled 2020 joiner (knowledge time 2021)."""

from datetime import UTC, date, datetime
from pathlib import Path

import pytest

from trp.domain.identifiers import SecurityId, new_security_id
from trp.universe.membership import UniverseMembership

BACKFILL_RECORDED = datetime(2021, 1, 15, tzinfo=UTC)


def build_ftse100() -> tuple[list[UniverseMembership], dict[str, SecurityId]]:
    ids = {
        "delisted": new_security_id(),
        "reentrant": new_security_id(),
        "current": new_security_id(),
        "backfilled": new_security_id(),
    }

    def spell(
        key: str, valid_from: date, valid_to: date | None = None, **kw: object
    ) -> UniverseMembership:
        return UniverseMembership(
            universe="FTSE100",
            security_id=ids[key],
            valid_from=valid_from,
            valid_to=valid_to,
            source="test-fixture",
            **kw,  # type: ignore[arg-type]
        )

    records = [
        spell("delisted", date(2005, 1, 4), date(2018, 1, 15)),
        spell("reentrant", date(2010, 1, 4), date(2015, 6, 1)),
        spell("reentrant", date(2019, 6, 24)),
        spell("current", date(2001, 3, 1)),
        spell("backfilled", date(2020, 3, 23), recorded_at=BACKFILL_RECORDED),
    ]
    return records, ids


@pytest.fixture
def stored_ftse100(tmp_path: Path) -> tuple[Path, dict[str, SecurityId]]:
    from trp.universe.storage import write_universe

    records, ids = build_ftse100()
    write_universe(records, tmp_path, known_security_ids=set(ids.values()))
    return tmp_path, ids
