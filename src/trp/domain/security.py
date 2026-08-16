"""Security master domain model: entities, securities, listings, status history.

See docs/DATA_MODEL.md. All models are frozen (immutable value objects); time-varying facts
are separate effective-dated records, never mutated fields. A change is a new record.
"""

from datetime import date, datetime
from enum import StrEnum
from typing import Self

from pydantic import BaseModel, ConfigDict, Field, model_validator

from trp.domain.identifiers import EntityId, SecurityId


class FrozenModel(BaseModel):
    """Base for all domain records: immutable, no silent extra fields, strict-ish."""

    model_config = ConfigDict(frozen=True, extra="forbid", str_strip_whitespace=True)


def revalidated_copy[M: BaseModel](model: M, **updates: object) -> M:
    """A copy with fields changed, passed through **full validation**.

    ``model_copy(update=...)`` skips validators and must not be used on domain records —
    it would allow invalid ranges and inconsistent aggregates to be constructed silently.
    """
    return type(model).model_validate({**model.model_dump(), **updates})


class SecurityType(StrEnum):
    ORDINARY = "ordinary"
    PREFERENCE = "preference"
    ADR = "adr"
    GDR = "gdr"
    INVESTMENT_TRUST = "investment_trust"
    ETF = "etf"


class SecurityStatus(StrEnum):
    ACTIVE = "active"
    SUSPENDED = "suspended"
    DELISTED = "delisted"
    ACQUIRED = "acquired"
    LIQUIDATED = "liquidated"


class DelistingReason(StrEnum):
    """Why a listing ended. An enum, not free text, because backtest accounting branches
    on it: failure implies (near-)zero proceeds, acquisition implies consideration paid."""

    FAILURE = "failure"
    ACQUISITION = "acquisition"
    VOLUNTARY = "voluntary"
    REGULATORY = "regulatory"
    EXCHANGE_MOVE = "exchange_move"


class Entity(FrozenModel):
    """A company or issuing entity. Name is the *current* label only — historical names
    belong in effective-dated records, and identity is always ``entity_id``."""

    entity_id: EntityId
    name: str = Field(min_length=1)
    country: str = Field(pattern=r"^[A-Z]{2}$", description="ISO 3166-1 alpha-2")


class Security(FrozenModel):
    """An instrument issued by an entity. ``security_id`` is immutable and never reused."""

    security_id: SecurityId
    entity_id: EntityId
    security_type: SecurityType
    name: str = Field(min_length=1)


class EffectiveDated(FrozenModel):
    """Mixin for bitemporal records.

    Event time: the fact was true over the half-open range [valid_from, valid_to).
    Knowledge time: we believed it from ``recorded_at`` until ``superseded_at``.

    ``recorded_at=None`` means knowledge time unknown (typically a bulk backfill); such
    records are treated as always-known. ``superseded_at`` set means a later revision
    replaced this record — the record is kept so earlier knowledge states remain
    reconstructable, but it is no longer current truth.
    """

    valid_from: date
    valid_to: date | None = None
    recorded_at: datetime | None = None
    superseded_at: datetime | None = None

    @model_validator(mode="after")
    def _range_is_positive(self) -> Self:
        if self.valid_to is not None and self.valid_to <= self.valid_from:
            raise ValueError(
                f"valid_to ({self.valid_to}) must be after valid_from ({self.valid_from})"
            )
        for label, stamp in (
            ("recorded_at", self.recorded_at),
            ("superseded_at", self.superseded_at),
        ):
            if stamp is not None and stamp.tzinfo is None:
                raise ValueError(f"{label} must be timezone-aware (UTC)")
        if (
            self.recorded_at is not None
            and self.superseded_at is not None
            and self.superseded_at <= self.recorded_at
        ):
            raise ValueError("superseded_at must be after recorded_at")
        return self

    @property
    def is_current(self) -> bool:
        return self.superseded_at is None


class SecurityStatusPeriod(EffectiveDated):
    """One span of a security's status history.

    ``related_security_id`` links to a counterparty where the status implies one — for
    ACQUIRED, the acquirer's security where it is in the master (left None for unknown or
    unlisted acquirers rather than inventing an entity).
    """

    security_id: SecurityId
    status: SecurityStatus
    reason: str | None = None
    related_security_id: SecurityId | None = None


class Listing(EffectiveDated):
    """A security trading on an exchange for a period.

    ``currency`` is the quote currency as the exchange quotes it — for LSE ordinaries that
    is usually GBX (pence sterling). Conversion policy is QNT-017; storing the truth as
    quoted avoids silent unit errors.
    """

    security_id: SecurityId
    mic: str = Field(pattern=r"^[A-Z0-9]{4}$", description="ISO 10383 market identifier code")
    currency: str = Field(pattern=r"^[A-Z]{3}$", description="ISO 4217 or GBX for pence")
    delisting_reason: DelistingReason | None = None

    @model_validator(mode="after")
    def _delisting_requires_end(self) -> Self:
        if self.delisting_reason is not None and self.valid_to is None:
            raise ValueError("delisting_reason requires a closed range (valid_to set)")
        return self
