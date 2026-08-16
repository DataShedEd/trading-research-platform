"""EODHD adapter. Transport, auth, pagination only — no semantics.

Tier assumed: whatever the owner's key is entitled to — the adapter declares the full
published capability set and lets entitlement failures surface honestly as HTTP 4xx
(``ProviderUnavailableError``); the first real run measures the actual tier (the
``/api/user`` endpoint reports the subscription and is used by the smoke-run probe, not
by this adapter). Endpoints used, all returning top-level JSON arrays or objects passed
through verbatim:

- ``GET /api/eod/{TICKER}.{EXCH}?from=&to=&period=d&fmt=json`` — daily bars with
  ``adjusted_close`` alongside raw OHLC.
- ``GET /api/splits/{TICKER}.{EXCH}?fmt=json`` and ``GET /api/div/{TICKER}.{EXCH}`` —
  corporate actions; ``corporate_actions`` yields the two responses as two pages.
- ``GET /api/fundamentals/{TICKER}.{EXCH}`` — one large object (``General``,
  ``Financials`` with per-period ``filing_date``); the payload parsers read the dialect.
- ``GET /api/exchange-symbol-list/{EXCH}?fmt=json`` — securities; with ``delisted=1``,
  the delisted list — **the single highest-value call in the bake-off** (UK delisted
  coverage is the platform's survivorship-bias litmus test).

Symbol convention: harness ``TICKER:MIC`` → EODHD ``TICKER.{exchange code}`` via an
explicit MIC map (XLON→LSE, XNYS/XNAS→US, XETR→XETRA). ``financial_periods`` has no
distinct endpoint → ``ProviderCapabilityError``.

Auth: EODHD only accepts the token as the ``api_token`` query parameter. It is attached
at request time ONLY — it appears in no stored payload params, no endpoint string, no log
and no exception message (the raw store's credential denylist is a second line of
defence, not the first).
"""

import time
from collections.abc import Callable, Iterator
from datetime import date

import httpx

from trp.config import load_settings
from trp.providers.adapters._http import get_with_retries, split_symbol
from trp.providers.base import (
    Dataset,
    MarketDataProvider,
    ProviderUnavailableError,
    RawPayload,
)

MIC_TO_EXCHANGE = {"XLON": "LSE", "XNYS": "US", "XNAS": "US", "XETR": "XETRA"}
_DEFAULT_EXCHANGES = ("LSE", "US")  # when no exchange is specified, page over these


class EodhdProvider(MarketDataProvider):
    name = "eodhd"
    version = "1.0"
    capabilities = frozenset(
        {
            Dataset.SECURITIES,
            Dataset.PRICES,
            Dataset.CORPORATE_ACTIONS,
            Dataset.FUNDAMENTALS,
            Dataset.DELISTED_SECURITIES,
        }
    )

    def __init__(
        self,
        api_key: str | None = None,
        *,
        transport: httpx.BaseTransport | None = None,
        sleep: Callable[[float], None] = time.sleep,
    ) -> None:
        if api_key is None:
            secret = load_settings().eodhd_api_key
            if secret is None:
                raise ProviderUnavailableError("eodhd: no API key (set TRP_EODHD_API_KEY)")
            api_key = secret.get_secret_value()
        self._token = api_key
        self._sleep = sleep
        self._client = httpx.Client(
            base_url="https://eodhd.com/api",
            headers={"Accept": "application/json"},
            timeout=60.0,
            transport=transport,
        )

    def _fetch(
        self, path: str, query: dict[str, str], meta: dict[str, str]
    ) -> Iterator[RawPayload]:
        """Token attached to the request only; stored params are ``query | meta``."""
        content = get_with_retries(
            self._client,
            self.name,
            path,
            {**query, "api_token": self._token},
            sleep=self._sleep,
        )
        if content is None:  # 404: genuinely absent — empty result, not an error
            return
        yield RawPayload(content=content, endpoint=path, params={**query, **meta})

    def _eodhd_symbol(self, symbol: str) -> str:
        ticker, mic = split_symbol(symbol)
        if mic is None:
            return ticker
        exchange = MIC_TO_EXCHANGE.get(mic)
        if exchange is None:
            raise ProviderUnavailableError(f"eodhd: no exchange code mapping for MIC {mic!r}")
        return f"{ticker}.{exchange}"

    def _exchanges(self, exchange: str | None) -> tuple[str, ...]:
        if exchange is None:
            return _DEFAULT_EXCHANGES
        return (MIC_TO_EXCHANGE.get(exchange, exchange),)

    def securities(self, *, exchange: str | None = None) -> Iterator[RawPayload]:
        self.require(Dataset.SECURITIES)
        for code in self._exchanges(exchange):
            yield from self._fetch(
                f"/exchange-symbol-list/{code}", {"fmt": "json"}, {"exchange": code}
            )

    def prices(self, symbol: str, start: date, end: date) -> Iterator[RawPayload]:
        self.require(Dataset.PRICES)
        return self._fetch(
            f"/eod/{self._eodhd_symbol(symbol)}",
            {"from": start.isoformat(), "to": end.isoformat(), "period": "d", "fmt": "json"},
            {"symbol": symbol},
        )

    def corporate_actions(self, symbol: str, start: date, end: date) -> Iterator[RawPayload]:
        self.require(Dataset.CORPORATE_ACTIONS)
        eodhd_symbol = self._eodhd_symbol(symbol)
        window = {"from": start.isoformat(), "to": end.isoformat(), "fmt": "json"}
        yield from self._fetch(f"/splits/{eodhd_symbol}", window, {"symbol": symbol})
        yield from self._fetch(f"/div/{eodhd_symbol}", window, {"symbol": symbol})

    def fundamentals(self, symbol: str) -> Iterator[RawPayload]:
        self.require(Dataset.FUNDAMENTALS)
        return self._fetch(
            f"/fundamentals/{self._eodhd_symbol(symbol)}", {"fmt": "json"}, {"symbol": symbol}
        )

    def financial_periods(self, symbol: str) -> Iterator[RawPayload]:
        self.require(Dataset.FINANCIAL_PERIODS)
        return iter(())

    def delisted_securities(self, *, exchange: str | None = None) -> Iterator[RawPayload]:
        self.require(Dataset.DELISTED_SECURITIES)
        for code in self._exchanges(exchange):
            yield from self._fetch(
                f"/exchange-symbol-list/{code}",
                {"fmt": "json", "delisted": "1"},
                {"exchange": code},
            )
