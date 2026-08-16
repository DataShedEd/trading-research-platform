"""Builds the lifecycle-fixture security master from tests/fixtures/security_master/.

The fixture file is the deliverable: expected results are data (probe rows), hand-derived
from each company's narrative, so adding a case means adding a row, not writing code.
"""

import json
from datetime import date, datetime
from pathlib import Path
from typing import Any

import pytest

from trp.domain import (
    Acquisition,
    DelistingReason,
    Entity,
    EntityRename,
    IdentifierKind,
    IdentifierRecord,
    Listing,
    Security,
    SecurityId,
    SecurityMaster,
    SecurityStatus,
    SecurityStatusPeriod,
    SecurityType,
    TickerChange,
    apply_event,
    new_entity_id,
    new_security_id,
)
from trp.domain.changes import Delisting

FIXTURE_PATH = Path(__file__).parent.parent / "fixtures" / "security_master" / "lifecycles.json"


def _dt(value: str) -> datetime:
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


def build_lifecycle_master() -> tuple[SecurityMaster, dict[str, SecurityId]]:
    spec: dict[str, Any] = json.loads(FIXTURE_PATH.read_text())
    ids: dict[str, SecurityId] = {}
    entities, securities, listings, statuses = [], [], [], []
    identifiers: list[IdentifierRecord] = []
    deferred: list[IdentifierRecord] = []

    for key, company in spec["companies"].items():
        entity_id, security_id = new_entity_id(), new_security_id()
        ids[key] = security_id
        listed = date.fromisoformat(company["listing"]["valid_from"])
        entities.append(
            Entity(
                entity_id=entity_id,
                name=company["entity"]["name"],
                country=company["entity"]["country"],
            )
        )
        securities.append(
            Security(
                security_id=security_id,
                entity_id=entity_id,
                security_type=SecurityType.ORDINARY,
                name=f"{company['entity']['name']} ordinary",
            )
        )
        listings.append(
            Listing(
                security_id=security_id,
                mic=company["listing"]["mic"],
                currency=company["listing"]["currency"],
                valid_from=listed,
            )
        )
        statuses.append(
            SecurityStatusPeriod(
                security_id=security_id, status=SecurityStatus.ACTIVE, valid_from=listed
            )
        )
        record = IdentifierRecord(
            security_id=security_id,
            kind=IdentifierKind.TICKER,
            value=company["ticker"]["value"],
            mic=company["listing"]["mic"],
            valid_from=date.fromisoformat(company["ticker"]["valid_from"]),
            recorded_at=(
                _dt(company["ticker"]["recorded_at"])
                if "recorded_at" in company["ticker"]
                else None
            ),
            source="fixture",
        )
        # Reused tickers only become assignable once an event frees them; defer those
        # past event replay, mirroring the ordering a real ingestion pipeline faces.
        (deferred if company["ticker"].get("deferred") else identifiers).append(record)

    master = SecurityMaster(
        entities=tuple(entities),
        securities=tuple(securities),
        listings=tuple(listings),
        status_periods=tuple(statuses),
        identifiers=tuple(identifiers),
    )

    entity_by_key = {key: e.entity_id for key, e in zip(spec["companies"], entities, strict=True)}
    for event in spec["events"]:
        sid = ids[event["company"]]
        match event["type"]:
            case "rename":
                master = apply_event(
                    master,
                    EntityRename(
                        entity_id=entity_by_key[event["company"]],
                        new_name=event["new_name"],
                        effective=date(2015, 6, 1),
                        source="fixture",
                    ),
                )
            case "ticker_change":
                master = apply_event(
                    master,
                    TickerChange(
                        security_id=sid,
                        mic=event["mic"],
                        new_ticker=event["new_ticker"],
                        effective=date.fromisoformat(event["effective"]),
                        source="fixture",
                    ),
                    knowledge_time=_dt(event["knowledge_time"]),
                )
            case "delisting_failure":
                master = apply_event(
                    master,
                    Delisting(
                        security_id=sid,
                        reason=DelistingReason.FAILURE,
                        detail=event["detail"],
                        effective=date.fromisoformat(event["effective"]),
                        source="fixture",
                    ),
                    knowledge_time=_dt(event["knowledge_time"]),
                )
            case "acquisition":
                master = apply_event(
                    master,
                    Acquisition(
                        security_id=sid,
                        acquirer_security_id=ids[event["acquirer"]],
                        effective=date.fromisoformat(event["effective"]),
                        source="fixture",
                    ),
                    knowledge_time=_dt(event["knowledge_time"]),
                )
            case other:
                raise ValueError(f"unknown fixture event type {other!r}")
    if deferred:
        master = SecurityMaster(
            entities=master.entities,
            securities=master.securities,
            listings=master.listings,
            status_periods=master.status_periods,
            identifiers=(*master.identifiers, *deferred),
        )
    return master, ids


@pytest.fixture(scope="session")
def lifecycle() -> tuple[SecurityMaster, dict[str, SecurityId]]:
    return build_lifecycle_master()


def load_probes() -> list[dict[str, Any]]:
    return list(json.loads(FIXTURE_PATH.read_text())["probes"])
