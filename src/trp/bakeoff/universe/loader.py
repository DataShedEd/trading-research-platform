"""Typed loader for the validation universe specification.

The universe is a versioned data file (``validation_universe.json``) of deliberately
awkward securities with mechanically-checkable expected facts. Every fact carries the
source it was verified against and the verification date; facts whose precision could
not be fully confirmed at authoring time carry ``needs_verification=True`` and MUST be
re-verified against a primary source before being used to score a provider — a wrong
"known-correct" expectation is worse than none.

Identifier conventions mirror the security master (QNT-006/007): tickers carry validity
ranges, ISIN/SEDOL check digits are validated where present, and a genuinely unknown
identifier is recorded explicitly as null rather than omitted.
"""

import json
from datetime import date
from decimal import Decimal
from enum import StrEnum
from functools import lru_cache
from pathlib import Path
from typing import Annotated, Literal, Self

from pydantic import Field, model_validator

from trp.domain.identifier_validation import validate_isin, validate_sedol
from trp.domain.security import DelistingReason, FrozenModel

SPEC_PATH = Path(__file__).parent / "validation_universe.json"


class Market(StrEnum):
    UK = "uk"
    US = "us"
    EU = "eu"


class AwkwardProperty(StrEnum):
    LONG_LIVED = "long_lived"
    FAILURE = "failure"
    ACQUISITION = "acquisition"
    TICKER_CHANGE = "ticker_change"
    SPLIT = "split"
    CONSOLIDATION = "consolidation"
    SPECIAL_DIVIDEND = "special_dividend"
    RIGHTS_ISSUE = "rights_issue"
    RESTATEMENT = "restatement"
    NON_GBP_REPORTER = "non_gbp_reporter"


class UniverseError(Exception):
    pass


class Identifier(FrozenModel):
    kind: Literal["isin", "sedol", "ticker"]
    value: str | None  # explicit null = genuinely unknown, and that gap is itself data
    mic: str | None = None
    valid_from: date | None = None
    valid_to: date | None = None

    @model_validator(mode="after")
    def _checksums(self) -> Self:
        if self.value is not None:
            if self.kind == "isin":
                validate_isin(self.value)
            elif self.kind == "sedol":
                validate_sedol(self.value)
            elif self.kind == "ticker" and self.mic is None:
                raise ValueError("ticker identifiers require a mic")
        return self


class FactBase(FrozenModel):
    source: str = Field(min_length=1, description="primary source: RNS, filing, exchange notice")
    verified_on: date
    needs_verification: bool = False


class DelistingFact(FactBase):
    fact: Literal["delisting"] = "delisting"
    effective: date
    reason: DelistingReason


class SplitFact(FactBase):
    fact: Literal["split"] = "split"
    ex_date: date
    new_shares: int = Field(gt=0)
    old_shares: int = Field(gt=0)


class DividendFact(FactBase):
    fact: Literal["dividend"] = "dividend"
    ex_date: date
    amount: Decimal = Field(gt=0)
    unit: str = Field(pattern=r"^[A-Z]{3}$", description="GBX vs GBP stated explicitly")
    special: bool = False


class TickerChangeFact(FactBase):
    fact: Literal["ticker_change"] = "ticker_change"
    effective: date
    old_ticker: str
    new_ticker: str
    mic: str


class RightsIssueFact(FactBase):
    fact: Literal["rights_issue"] = "rights_issue"
    ex_date: date
    new_shares: int = Field(gt=0)
    old_shares: int = Field(gt=0)
    subscription_price: Decimal = Field(gt=0)
    unit: str = Field(pattern=r"^[A-Z]{3}$")


class AcquisitionFact(FactBase):
    fact: Literal["acquisition"] = "acquisition"
    effective: date
    acquirer: str
    cash_per_share: Decimal | None = None
    unit: str | None = Field(default=None, pattern=r"^[A-Z]{3}$")


class RestatementFact(FactBase):
    """Expressed in point-in-time terms (what was knowable when) so QNT-035 can check it."""

    fact: Literal["restatement"] = "restatement"
    line_item: str
    period_end: date
    original_value: Decimal
    restated_value: Decimal
    unit: str = Field(pattern=r"^[A-Z]{3}$")
    original_available: date
    restatement_available: date

    @model_validator(mode="after")
    def _ordered(self) -> Self:
        if self.restatement_available <= self.original_available:
            raise ValueError("restatement must become available after the original")
        return self


Fact = Annotated[
    DelistingFact
    | SplitFact
    | DividendFact
    | TickerChangeFact
    | RightsIssueFact
    | AcquisitionFact
    | RestatementFact,
    Field(discriminator="fact"),
]


class UniverseEntry(FrozenModel):
    key: str = Field(pattern=r"^[a-z0-9-]+$")
    entity_name: str = Field(min_length=1)
    market: Market
    mic: str = Field(pattern=r"^[A-Z0-9]{4}$")
    quote_currency: str = Field(pattern=r"^[A-Z]{3}$")
    reporting_currency: str = Field(pattern=r"^[A-Z]{3}$")
    identifiers: tuple[Identifier, ...]
    properties: tuple[AwkwardProperty, ...] = Field(min_length=1)
    facts: tuple[Fact, ...] = ()
    notes: str | None = None

    @model_validator(mode="after")
    def _lifecycle_consistent(self) -> Self:
        delistings = [f for f in self.facts if isinstance(f, DelistingFact)]
        if delistings:
            end = min(f.effective for f in delistings)
            for f in self.facts:
                event_date = getattr(f, "ex_date", None)
                if event_date is not None and event_date >= end:
                    raise ValueError(
                        f"{self.key}: fact dated {event_date} on or after delisting {end}"
                    )
        return self


class ValidationUniverse(FrozenModel):
    version: str = Field(min_length=1)
    entries: tuple[UniverseEntry, ...]

    @model_validator(mode="after")
    def _coherent(self) -> Self:
        keys = [e.key for e in self.entries]
        if len(set(keys)) != len(keys):
            raise ValueError("duplicate entry keys")
        if list(keys) != sorted(keys):
            raise ValueError("entries must be sorted by key for deterministic ordering")
        return self

    def by_market(self, market: Market) -> tuple[UniverseEntry, ...]:
        return tuple(e for e in self.entries if e.market is market)

    def by_property(self, prop: AwkwardProperty) -> tuple[UniverseEntry, ...]:
        return tuple(e for e in self.entries if prop in e.properties)


@lru_cache(maxsize=1)
def load_universe(path: Path = SPEC_PATH) -> ValidationUniverse:
    try:
        payload = json.loads(path.read_text())
    except (OSError, json.JSONDecodeError) as exc:
        raise UniverseError(f"cannot load validation universe from {path}: {exc}") from exc
    return ValidationUniverse.model_validate(payload)
