from datetime import date

import pytest

from tests.fakes.provider import FakeProvider, NoFundamentalsProvider
from trp.providers.base import (
    Dataset,
    MarketDataProvider,
    ProviderCapabilityError,
    ProviderRateLimitError,
    RawPayload,
)


def payload(body: bytes = b"{}") -> RawPayload:
    return RawPayload(content=body, endpoint="/test", params={"symbol": "TST"})


def test_incomplete_adapter_cannot_be_instantiated() -> None:
    class Partial(MarketDataProvider):  # missing every abstract method
        name = "partial"
        version = "0"
        capabilities = frozenset()

    with pytest.raises(TypeError):
        Partial()  # type: ignore[abstract]


def test_unsupported_dataset_is_a_distinct_error_not_an_empty_result() -> None:
    provider = NoFundamentalsProvider()
    with pytest.raises(ProviderCapabilityError, match="does not support fundamentals"):
        list(provider.fundamentals("TST"))
    # Supported-but-empty is a different, legitimate outcome.
    assert list(provider.prices("TST", date(2020, 1, 1), date(2020, 1, 31))) == []


def test_pagination_yields_pages_in_order() -> None:
    pages = [payload(b'{"page":1}'), payload(b'{"page":2}')]
    provider = FakeProvider({Dataset.PRICES: list(pages)})
    got = list(provider.prices("TST", date(2020, 1, 1), date(2020, 1, 31)))
    assert [p.content for p in got] == [b'{"page":1}', b'{"page":2}']


def test_mid_pagination_rate_limit_surfaces_after_earlier_pages() -> None:
    provider = FakeProvider(
        {Dataset.PRICES: [payload(b'{"page":1}'), ProviderRateLimitError("fake", 30.0)]}
    )
    it = provider.prices("TST", date(2020, 1, 1), date(2020, 1, 31))
    assert next(it).content == b'{"page":1}'
    with pytest.raises(ProviderRateLimitError) as excinfo:
        next(it)
    assert excinfo.value.retry_after_seconds == 30.0
