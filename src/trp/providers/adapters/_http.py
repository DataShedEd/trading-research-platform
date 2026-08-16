"""Shared HTTP plumbing for provider adapters: retries, backoff, error taxonomy.

Adapters remain transport-only (docs/ARCHITECTURE.md). Mapping is uniform:
HTTP 200 → verbatim bytes; 404 → ``None`` (genuinely absent — an empty result, never an
error); 429 → :class:`ProviderRateLimitError` honouring ``Retry-After``; 401/403 →
:class:`ProviderUnavailableError` (key/entitlement — the message never contains the key);
5xx and transport errors retry with bounded exponential backoff before giving up as
unavailable. The injectable ``sleep`` keeps tests instant.
"""

import logging
import time
from collections.abc import Callable

import httpx

from trp.providers.base import ProviderRateLimitError, ProviderUnavailableError

logger = logging.getLogger(__name__)

_MAX_ATTEMPTS = 4  # 1 try + 3 retries


def get_with_retries(
    client: httpx.Client,
    provider: str,
    path: str,
    params: dict[str, str],
    *,
    sleep: Callable[[float], None] = time.sleep,
) -> bytes | None:
    last_error: str = "no attempt made"
    for attempt in range(_MAX_ATTEMPTS):
        try:
            response = client.get(path, params=params)
        except (httpx.TimeoutException, httpx.TransportError) as exc:
            last_error = f"transport error: {type(exc).__name__}"
            logger.warning("%s %s attempt %d: %s", provider, path, attempt + 1, last_error)
            if attempt < _MAX_ATTEMPTS - 1:
                sleep(2.0**attempt)
            continue

        if response.status_code == 200:
            return response.content
        if response.status_code == 404:
            return None
        if response.status_code == 429:
            retry_after = response.headers.get("Retry-After")
            raise ProviderRateLimitError(provider, float(retry_after) if retry_after else None)
        if response.status_code in (401, 402, 403):
            raise ProviderUnavailableError(
                f"{provider}: HTTP {response.status_code} on {path} — "
                "check the API key and the subscribed tier's entitlement for this endpoint"
            )
        if 500 <= response.status_code < 600:
            last_error = f"HTTP {response.status_code}"
            if attempt < _MAX_ATTEMPTS - 1:
                sleep(2.0**attempt)
            continue
        raise ProviderUnavailableError(
            f"{provider}: unexpected HTTP {response.status_code} on {path}"
        )
    raise ProviderUnavailableError(
        f"{provider}: {path} failed after {_MAX_ATTEMPTS} attempts ({last_error})"
    )


def split_symbol(symbol: str) -> tuple[str, str | None]:
    """The harness's ``TICKER:MIC`` convention → (ticker, mic or None)."""
    ticker, _, mic = symbol.partition(":")
    return ticker, (mic or None)
