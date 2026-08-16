"""Tiingo adapter (Starter/free tier). Transport, auth, pagination only — no semantics.

Tier assumed: **Starter (free)**. Endpoints used and their observed shapes:

- ``GET /tiingo/daily/{ticker}/prices?startDate=&endDate=&format=json`` — top-level JSON
  array of daily rows carrying BOTH unadjusted (``open``…``close``) and adjusted
  (``adjOpen``…``adjClose``) fields plus inline actions (``divCash``, ``splitFactor``).
  Passed through verbatim; the payload parsers understand the dialect.
- Corporate actions have no separate Starter endpoint: ``corporate_actions`` fetches the
  same daily series, because that IS where Tiingo carries splits and dividends. The
  payload is byte-identical to a prices fetch by design.
- ``GET /tiingo/fundamentals/{ticker}/statements`` — free tier covers the DOW 30 only;
  entitlement failures surface as HTTP 4xx → ``ProviderUnavailableError``.

Deliberately unsupported on this tier (``ProviderCapabilityError``, never empty results):
``securities`` (Tiingo's supported-tickers list is a bulk ZIP download, not an API page),
``financial_periods`` (no distinct endpoint), ``delisted_securities`` (no endpoint — this
is precisely why Tiingo is the US cross-check, not a candidate for the UK platform).

Market scope: US listings only. Non-US symbols simply 404 → a successful empty result,
recorded with the symbol form attempted.

Auth: ``Authorization: Token <key>`` header (never a query parameter, never in stored
params or endpoint strings). Observed limits (Starter): hourly and daily request caps —
HTTP 429 maps to ``ProviderRateLimitError``.
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


class TiingoProvider(MarketDataProvider):
    name = "tiingo"
    version = "1.0"
    capabilities = frozenset({Dataset.PRICES, Dataset.CORPORATE_ACTIONS, Dataset.FUNDAMENTALS})

    def __init__(
        self,
        api_key: str | None = None,
        *,
        transport: httpx.BaseTransport | None = None,
        sleep: Callable[[float], None] = time.sleep,
    ) -> None:
        if api_key is None:
            secret = load_settings().tiingo_api_key
            if secret is None:
                raise ProviderUnavailableError("tiingo: no API key (set TRP_TIINGO_API_KEY)")
            api_key = secret.get_secret_value()
        self._sleep = sleep
        self._client = httpx.Client(
            base_url="https://api.tiingo.com",
            headers={"Authorization": f"Token {api_key}", "Accept": "application/json"},
            timeout=30.0,
            transport=transport,
        )

    def _fetch(
        self, path: str, query: dict[str, str], meta: dict[str, str]
    ) -> Iterator[RawPayload]:
        """``query`` is sent; ``query | meta`` is stored as the payload's logical params."""
        content = get_with_retries(self._client, self.name, path, query, sleep=self._sleep)
        if content is None:  # 404: genuinely absent (e.g. a non-US symbol) — empty, not error
            return
        yield RawPayload(content=content, endpoint=path, params={**query, **meta})

    def securities(self, *, exchange: str | None = None) -> Iterator[RawPayload]:
        self.require(Dataset.SECURITIES)
        return iter(())

    def prices(self, symbol: str, start: date, end: date) -> Iterator[RawPayload]:
        self.require(Dataset.PRICES)
        ticker, _mic = split_symbol(symbol)
        return self._fetch(
            f"/tiingo/daily/{ticker.lower()}/prices",
            {
                "startDate": start.isoformat(),
                "endDate": end.isoformat(),
                "format": "json",
            },
            {"symbol": symbol},
        )

    def corporate_actions(self, symbol: str, start: date, end: date) -> Iterator[RawPayload]:
        self.require(Dataset.CORPORATE_ACTIONS)
        # Tiingo carries splits/dividends inline on the daily series (module docstring).
        return self.prices(symbol, start, end)

    def fundamentals(self, symbol: str) -> Iterator[RawPayload]:
        self.require(Dataset.FUNDAMENTALS)
        ticker, _mic = split_symbol(symbol)
        return self._fetch(
            f"/tiingo/fundamentals/{ticker.lower()}/statements", {}, {"symbol": symbol}
        )

    def financial_periods(self, symbol: str) -> Iterator[RawPayload]:
        self.require(Dataset.FINANCIAL_PERIODS)
        return iter(())

    def delisted_securities(self, *, exchange: str | None = None) -> Iterator[RawPayload]:
        self.require(Dataset.DELISTED_SECURITIES)
        return iter(())
