"""The common provider interface every adapter implements.

Layering (docs/ARCHITECTURE.md): adapters handle transport, auth, pagination and rate
limits ONLY. They return provider-shaped payloads — verbatim response bytes — never
canonical models; all semantic work happens in ``trp.canonical`` from the raw layer.
Resisting normalisation here is the point: raw fidelity is what makes reprocessing and
the bake-off's evidence trail possible.

Every method over historical data takes an explicit range; nothing returns "the current
view" implicitly. Fundamentals return the provider's full filing history including
whatever announcement/filing timestamps it offers, untouched, so their presence can be
measured (QNT-035) and ``available_at`` derived honestly (QNT-020).
"""

from abc import ABC, abstractmethod
from collections.abc import Iterator
from datetime import date
from enum import StrEnum
from typing import ClassVar

from pydantic import Field

from trp.domain.security import FrozenModel


class Dataset(StrEnum):
    SECURITIES = "securities"
    PRICES = "prices"
    CORPORATE_ACTIONS = "corporate_actions"
    FUNDAMENTALS = "fundamentals"
    FINANCIAL_PERIODS = "financial_periods"
    DELISTED_SECURITIES = "delisted_securities"


class ProviderError(Exception):
    """Base for provider-layer failures."""


class ProviderCapabilityError(ProviderError):
    """The provider does not offer this dataset at all.

    Distinct from an empty result: "no such data exists here" must never be scored by the
    bake-off as "data missing".
    """

    def __init__(self, provider: str, dataset: Dataset) -> None:
        super().__init__(f"provider {provider!r} does not support {dataset.value}")


class ProviderRateLimitError(ProviderError):
    """We were throttled; the request may succeed later."""

    def __init__(self, provider: str, retry_after_seconds: float | None = None) -> None:
        self.retry_after_seconds = retry_after_seconds
        super().__init__(f"provider {provider!r} rate-limited (retry_after={retry_after_seconds})")


class ProviderUnavailableError(ProviderError):
    """Transport-level failure: network, 5xx, timeout."""


class RawPayload(FrozenModel):
    """One response as received: verbatim bytes plus the request that produced them.

    ``params`` must already exclude credentials — adapters pass the logical request
    parameters, never auth material. ``content`` is untouched: no reformatting, key
    reordering, coercion or pretty-printing.
    """

    content: bytes
    content_type: str = "application/json"
    endpoint: str = Field(min_length=1)
    params: dict[str, str] = Field(default_factory=dict)


class MarketDataProvider(ABC):
    """Abstract interface for a market-data provider.

    Class-level identity: ``name`` (stable slug used in raw paths), ``version`` (adapter
    version, recorded with every payload), ``capabilities`` (datasets genuinely offered).
    Methods yield one ``RawPayload`` per response page; pagination is the adapter's
    concern and invisible to callers beyond the iterator shape.
    """

    name: ClassVar[str]
    version: ClassVar[str]
    capabilities: ClassVar[frozenset[Dataset]]

    def require(self, dataset: Dataset) -> None:
        """Raise ProviderCapabilityError unless ``dataset`` is genuinely supported."""
        if dataset not in self.capabilities:
            raise ProviderCapabilityError(self.name, dataset)

    @abstractmethod
    def securities(self, *, exchange: str | None = None) -> Iterator[RawPayload]:
        """Listed-security metadata, optionally narrowed to one exchange. Paginated."""

    @abstractmethod
    def prices(self, symbol: str, start: date, end: date) -> Iterator[RawPayload]:
        """Daily bars for ``symbol`` over [start, end]. Paginated for long ranges."""

    @abstractmethod
    def corporate_actions(self, symbol: str, start: date, end: date) -> Iterator[RawPayload]:
        """Splits, dividends and other actions for ``symbol`` over [start, end]."""

    @abstractmethod
    def fundamentals(self, symbol: str) -> Iterator[RawPayload]:
        """The provider's full filing history for ``symbol``, timestamps untouched."""

    @abstractmethod
    def financial_periods(self, symbol: str) -> Iterator[RawPayload]:
        """Reported period metadata (period ends, announcement dates) where offered."""

    @abstractmethod
    def delisted_securities(self, *, exchange: str | None = None) -> Iterator[RawPayload]:
        """Securities no longer listed — the survivorship-bias litmus test. Paginated."""
