"""Adapter tests against stubbed transports — no live calls, ever.

Recorded-shape fixtures below mirror responses captured from public API documentation on
2026-08-16 (tokens redacted); byte fidelity is asserted against these exact bytes.
"""

from datetime import date

import httpx
import pytest

from trp.providers.adapters.eodhd import EodhdProvider
from trp.providers.adapters.tiingo import TiingoProvider
from trp.providers.base import (
    ProviderCapabilityError,
    ProviderRateLimitError,
    ProviderUnavailableError,
)

SENTINEL = "sk-SENTINEL-TOKEN-000"
START, END = date(2020, 1, 1), date(2020, 12, 31)

# Deliberately odd spacing/ordering: fidelity means these exact bytes come back.
TIINGO_PRICES = (
    b'[{"date":"2020-08-31T00:00:00.000Z","close":129.04,  '
    b'"adjClose":127.31,"splitFactor":4.0,"divCash":0.0}]'
)
EODHD_EOD = b'[{"date": "2020-08-31","close": 129.04,"adjusted_close": 127.31,"volume": 225702700}]'
EODHD_SPLITS = b'[{"date": "2020-08-31", "split": "4.000000/1.000000"}]'
EODHD_DIVS = b'[{"date": "2020-08-07", "value": 0.82, "currency": "USD"}]'


class Recorder:
    def __init__(self, responses: dict[str, httpx.Response]) -> None:
        self.requests: list[httpx.Request] = []
        self._responses = responses

    def handler(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        for fragment, response in self._responses.items():
            if fragment in request.url.path:
                return response
        return httpx.Response(404, content=b"Not found")


def tiingo(recorder: Recorder, sleeps: list[float] | None = None) -> TiingoProvider:
    return TiingoProvider(
        SENTINEL,
        transport=httpx.MockTransport(recorder.handler),
        sleep=(sleeps.append if sleeps is not None else lambda _: None),
    )


def eodhd(recorder: Recorder, sleeps: list[float] | None = None) -> EodhdProvider:
    return EodhdProvider(
        SENTINEL,
        transport=httpx.MockTransport(recorder.handler),
        sleep=(sleeps.append if sleeps is not None else lambda _: None),
    )


class TestTiingo:
    def test_prices_verbatim_and_token_hygiene(self) -> None:
        recorder = Recorder({"/prices": httpx.Response(200, content=TIINGO_PRICES)})
        pages = list(tiingo(recorder).prices("AAPL:XNAS", START, END))
        (page,) = pages
        assert page.content == TIINGO_PRICES  # byte-identical
        assert page.params["symbol"] == "AAPL:XNAS"
        assert SENTINEL not in str(page.params)
        assert SENTINEL not in page.endpoint
        (request,) = recorder.requests
        assert request.url.path == "/tiingo/daily/aapl/prices"
        assert request.headers["Authorization"] == f"Token {SENTINEL}"
        assert SENTINEL not in str(request.url)  # header auth, never query

    def test_corporate_actions_is_the_inline_daily_series(self) -> None:
        recorder = Recorder({"/prices": httpx.Response(200, content=TIINGO_PRICES)})
        (page,) = list(tiingo(recorder).corporate_actions("AAPL:XNAS", START, END))
        assert page.content == TIINGO_PRICES

    def test_unknown_symbol_is_empty_not_error(self) -> None:
        recorder = Recorder({})  # everything 404s
        assert list(tiingo(recorder).prices("CLLN:XLON", START, END)) == []

    def test_unsupported_datasets_raise_capability_error(self) -> None:
        provider = tiingo(Recorder({}))
        with pytest.raises(ProviderCapabilityError):
            list(provider.delisted_securities())
        with pytest.raises(ProviderCapabilityError):
            list(provider.securities())
        with pytest.raises(ProviderCapabilityError):
            list(provider.financial_periods("AAPL:XNAS"))

    def test_rate_limit_maps_with_retry_after(self) -> None:
        recorder = Recorder({"/prices": httpx.Response(429, headers={"Retry-After": "60"})})
        with pytest.raises(ProviderRateLimitError) as excinfo:
            list(tiingo(recorder).prices("AAPL:XNAS", START, END))
        assert excinfo.value.retry_after_seconds == 60.0

    def test_5xx_retries_with_backoff_then_unavailable(self) -> None:
        sleeps: list[float] = []
        recorder = Recorder({"/prices": httpx.Response(503)})
        with pytest.raises(ProviderUnavailableError, match="failed after"):
            list(tiingo(recorder, sleeps).prices("AAPL:XNAS", START, END))
        assert sleeps == [1.0, 2.0, 4.0]  # bounded exponential backoff

    def test_auth_failure_message_never_contains_the_token(self) -> None:
        recorder = Recorder({"/prices": httpx.Response(403)})
        with pytest.raises(ProviderUnavailableError) as excinfo:
            list(tiingo(recorder).prices("AAPL:XNAS", START, END))
        assert SENTINEL not in str(excinfo.value)


class TestEodhd:
    def test_prices_verbatim_symbol_mapping_and_query_token_hygiene(self) -> None:
        recorder = Recorder({"/eod/": httpx.Response(200, content=EODHD_EOD)})
        (page,) = list(eodhd(recorder).prices("SHEL:XLON", START, END))
        assert page.content == EODHD_EOD
        assert SENTINEL not in str(page.params) and SENTINEL not in page.endpoint
        (request,) = recorder.requests
        assert request.url.path == "/api/eod/SHEL.LSE"  # MIC XLON -> LSE
        assert request.url.params["api_token"] == SENTINEL  # sent on the wire only

    def test_corporate_actions_yields_splits_then_dividends_pages(self) -> None:
        recorder = Recorder(
            {
                "/splits/": httpx.Response(200, content=EODHD_SPLITS),
                "/div/": httpx.Response(200, content=EODHD_DIVS),
            }
        )
        pages = list(eodhd(recorder).corporate_actions("AAPL:XNAS", START, END))
        assert [p.content for p in pages] == [EODHD_SPLITS, EODHD_DIVS]
        assert [p.endpoint for p in pages] == ["/splits/AAPL.US", "/div/AAPL.US"]

    def test_delisted_securities_uses_the_delisted_flag(self) -> None:
        recorder = Recorder(
            {"/exchange-symbol-list/": httpx.Response(200, content=b'[{"Code":"CLLN"}]')}
        )
        pages = list(eodhd(recorder).delisted_securities(exchange="XLON"))
        (request,) = recorder.requests
        assert request.url.path == "/api/exchange-symbol-list/LSE"
        assert request.url.params["delisted"] == "1"
        assert pages[0].params["exchange"] == "LSE"

    def test_no_exchange_pages_over_lse_and_us(self) -> None:
        recorder = Recorder({"/exchange-symbol-list/": httpx.Response(200, content=b"[]")})
        list(eodhd(recorder).securities())
        assert [r.url.path for r in recorder.requests] == [
            "/api/exchange-symbol-list/LSE",
            "/api/exchange-symbol-list/US",
        ]

    def test_unknown_mic_is_loud(self) -> None:
        with pytest.raises(ProviderUnavailableError, match="no exchange code mapping"):
            list(eodhd(Recorder({})).prices("SAP:XPAR", START, END))

    def test_financial_periods_unsupported(self) -> None:
        with pytest.raises(ProviderCapabilityError):
            list(eodhd(Recorder({})).financial_periods("AAPL:XNAS"))
