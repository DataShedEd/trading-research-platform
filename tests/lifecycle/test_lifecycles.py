"""Epic 2 regression harness: full company lifecycles played through every layer.

Every probe row from the fixture is asserted three ways: against the built master,
against a storage round-trip of it, and (for probes with ``as_of``) through the
point-in-time facade. If a downstream result ever looks wrong, run this first.
"""

from datetime import date
from pathlib import Path
from typing import Any

import pytest

from tests.lifecycle.conftest import _dt, load_probes
from trp.canonical.security_store import read_security_master, write_security_master
from trp.domain import (
    IdentifierKind,
    IdentifierResolver,
    PointInTimeSecurityMaster,
    SecurityId,
    SecurityMaster,
    SecurityStatus,
    UnknownIdentifier,
    status_on,
)

PROBES = load_probes()
PIT_PROBES = [p for p in PROBES if "as_of" in p]
CURRENT_PROBES = [p for p in PROBES if "as_of" not in p]


def run_probe(master: SecurityMaster, probe: dict[str, Any], ids: dict[str, SecurityId]) -> None:
    by_id = {v: k for k, v in ids.items()}
    on = date.fromisoformat(probe["on"]) if "on" in probe else None
    query = probe["query"]

    if query == "resolve":
        assert on is not None
        pit = PointInTimeSecurityMaster(master)

        def do() -> SecurityId:
            if "as_of" in probe:
                return pit.resolve(
                    probe["value"], IdentifierKind.TICKER, on, as_of=_dt(probe["as_of"])
                )
            return IdentifierResolver(master).resolve(probe["value"], IdentifierKind.TICKER, on)

        if probe.get("expect_error") == "unknown":
            with pytest.raises(UnknownIdentifier):
                do()
        else:
            assert by_id[do()] == probe["expect"]

    elif query == "status":
        assert on is not None
        result = status_on(master, ids[probe["company"]], on)
        expected = None if probe["expect"] is None else SecurityStatus(probe["expect"])
        assert result is expected

    elif query == "identifiers":
        assert on is not None
        records = IdentifierResolver(master).identifiers_for(
            ids[probe["company"]], on, IdentifierKind.TICKER
        )
        assert sorted(r.value for r in records) == sorted(probe["expect"])

    elif query == "acquirer":
        terminal = next(
            p
            for p in master.status_periods
            if p.is_current
            and p.security_id == ids[probe["company"]]
            and p.status is SecurityStatus.ACQUIRED
        )
        assert terminal.related_security_id == ids[probe["expect"]]

    else:
        raise ValueError(f"unknown probe query {query!r}")


@pytest.mark.parametrize("probe", PROBES, ids=[p["id"] for p in PROBES])
def test_probe_against_built_master(
    probe: dict[str, Any], lifecycle: tuple[SecurityMaster, dict[str, SecurityId]]
) -> None:
    master, ids = lifecycle
    run_probe(master, probe, ids)


@pytest.mark.parametrize("probe", PROBES, ids=[p["id"] for p in PROBES])
def test_probe_after_storage_round_trip(
    probe: dict[str, Any],
    lifecycle: tuple[SecurityMaster, dict[str, SecurityId]],
    tmp_path_factory: pytest.TempPathFactory,
) -> None:
    master, ids = lifecycle
    directory: Path = tmp_path_factory.getbasetemp() / "lifecycle-master"
    if not directory.exists():
        write_security_master(master, directory)
    run_probe(read_security_master(directory), probe, ids)


@pytest.mark.timetravel
@pytest.mark.parametrize("probe", PIT_PROBES, ids=[p["id"] for p in PIT_PROBES])
def test_knowledge_time_probes(
    probe: dict[str, Any], lifecycle: tuple[SecurityMaster, dict[str, SecurityId]]
) -> None:
    master, ids = lifecycle
    run_probe(master, probe, ids)
