"""A scriptable in-memory MarketDataProvider for tests. No network, ever.

Script each dataset with a list of payloads and/or exceptions: payloads are yielded as
pages; an exception in the list is raised at that point in the iteration (mid-pagination
failures, rate limits, outages). Calls are recorded for assertion.
"""

from collections.abc import Iterator
from datetime import date

from trp.providers.base import Dataset, MarketDataProvider, RawPayload

Scripted = RawPayload | Exception


class FakeProvider(MarketDataProvider):
    name = "fake"
    version = "0.0-test"
    capabilities = frozenset(Dataset)

    def __init__(self, script: dict[Dataset, list[Scripted]] | None = None) -> None:
        self._script = script or {}
        self.calls: list[tuple[Dataset, dict[str, object]]] = []

    def _serve(self, dataset: Dataset, **params: object) -> Iterator[RawPayload]:
        self.require(dataset)
        self.calls.append((dataset, params))
        for item in self._script.get(dataset, []):
            if isinstance(item, Exception):
                raise item
            yield item

    def securities(self, *, exchange: str | None = None) -> Iterator[RawPayload]:
        return self._serve(Dataset.SECURITIES, exchange=exchange)

    def prices(self, symbol: str, start: date, end: date) -> Iterator[RawPayload]:
        return self._serve(Dataset.PRICES, symbol=symbol, start=start, end=end)

    def corporate_actions(self, symbol: str, start: date, end: date) -> Iterator[RawPayload]:
        return self._serve(Dataset.CORPORATE_ACTIONS, symbol=symbol, start=start, end=end)

    def fundamentals(self, symbol: str) -> Iterator[RawPayload]:
        return self._serve(Dataset.FUNDAMENTALS, symbol=symbol)

    def financial_periods(self, symbol: str) -> Iterator[RawPayload]:
        return self._serve(Dataset.FINANCIAL_PERIODS, symbol=symbol)

    def delisted_securities(self, *, exchange: str | None = None) -> Iterator[RawPayload]:
        return self._serve(Dataset.DELISTED_SECURITIES, exchange=exchange)


class NoFundamentalsProvider(FakeProvider):
    """A provider that genuinely does not offer fundamentals or period metadata."""

    name = "fake-prices-only"
    capabilities = frozenset(Dataset) - {Dataset.FUNDAMENTALS, Dataset.FINANCIAL_PERIODS}
