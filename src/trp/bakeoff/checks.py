"""Check protocol and registry for the bake-off harness.

A check declares which dataset kinds and which awkward properties it applies to, and a
``criterion`` linking its results to the scoring rubric (QNT-030). Checks read raw
payload bytes — part of what is being measured is what the provider actually sends — and
return findings with human-readable evidence: expected, observed, explanation. A bare
boolean is useless to a reader adjudicating whether the provider or the expectation was
wrong.

Outcomes: ``pass`` / ``fail`` are self-evident; ``not_applicable`` (a split check on a
security that never split) is excluded from scoring denominators; ``error`` means the
check itself raised — captured with its traceback by the runner, never crashing the run.
"""

from abc import ABC, abstractmethod
from collections.abc import Sequence
from enum import StrEnum

from pydantic import Field

from trp.bakeoff.universe.loader import AwkwardProperty, UniverseEntry
from trp.domain.security import FrozenModel
from trp.providers.base import Dataset


class Outcome(StrEnum):
    PASS = "pass"
    FAIL = "fail"
    NOT_APPLICABLE = "not_applicable"
    ERROR = "error"


class Criterion(StrEnum):
    HISTORICAL_DEPTH = "historical_depth"
    DELISTED_COVERAGE = "delisted_coverage"
    CORPORATE_ACTION_ACCURACY = "corporate_action_accuracy"
    IDENTIFIER_STABILITY = "identifier_stability"
    PIT_FUNDAMENTALS = "pit_fundamentals"
    REVISION_HISTORY = "revision_history"
    API_RELIABILITY = "api_reliability"
    RATE_LIMITS_BULK = "rate_limits_bulk"
    LICENSING = "licensing"
    COST = "cost"


class Finding(FrozenModel):
    """One check outcome with its evidence."""

    outcome: Outcome
    expected: str | None = None
    observed: str | None = None
    explanation: str = Field(min_length=1)


class CheckResult(FrozenModel):
    """A finding in context: which check, cell, criterion, and raw evidence produced it."""

    check: str
    criterion: Criterion
    provider: str
    security_key: str
    dataset: Dataset
    outcome: Outcome
    expected: str | None = None
    observed: str | None = None
    explanation: str
    raw_refs: tuple[str, ...] = ()


class Check(ABC):
    """Subclass, set the class attributes, implement ``run``. Register with
    :func:`register` — the runner picks checks up by dataset and awkward property
    without modification (QNT-034/035 extend here)."""

    name: str
    criterion: Criterion
    datasets: frozenset[Dataset]
    properties: frozenset[AwkwardProperty] | None = None  # None = applies to every entry

    def applies_to(self, entry: UniverseEntry, dataset: Dataset) -> bool:
        if dataset not in self.datasets:
            return False
        if self.properties is None:
            return True
        return bool(self.properties & set(entry.properties))

    @abstractmethod
    def run(self, entry: UniverseEntry, payloads: Sequence[bytes]) -> list[Finding]:
        """Evaluate the entry against the raw payload pages fetched for this cell."""


_REGISTRY: dict[str, Check] = {}


def register(check: Check) -> Check:
    if check.name in _REGISTRY:
        raise ValueError(f"check {check.name!r} already registered")
    _REGISTRY[check.name] = check
    return check


def registered_checks() -> tuple[Check, ...]:
    return tuple(_REGISTRY[name] for name in sorted(_REGISTRY))


def clear_registry() -> None:
    """Test hook."""
    _REGISTRY.clear()


class PayloadPresenceCheck(Check):
    """Reference check: the provider returned at least one non-empty payload page."""

    name = "payload_presence"
    criterion = Criterion.API_RELIABILITY
    datasets = frozenset(Dataset)
    properties = None

    def run(self, entry: UniverseEntry, payloads: Sequence[bytes]) -> list[Finding]:
        if any(page.strip() for page in payloads):
            return [
                Finding(
                    outcome=Outcome.PASS,
                    expected="non-empty response",
                    observed=f"{len(payloads)} page(s)",
                    explanation="provider returned data for the request",
                )
            ]
        return [
            Finding(
                outcome=Outcome.FAIL,
                expected="non-empty response",
                observed="no data",
                explanation="provider returned nothing for a security it should know",
            )
        ]
