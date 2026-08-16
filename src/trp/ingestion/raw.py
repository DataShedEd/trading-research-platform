"""The raw ingestion layer: provider payloads stored verbatim, immutably, append-only.

Layout, navigable by a human:

    data/raw/<provider>/<dataset>/<params_hash>/<fetched_at>-<n>.<ext>       # payload bytes
    data/raw/<provider>/<dataset>/<params_hash>/<fetched_at>-<n>.meta.json   # sidecar

Re-fetching the same endpoint and parameters appends a new timestamped record; nothing is
ever overwritten and there is no delete method. When licensing forbids retaining a payload
(``retain=False``), only the sidecar is written, carrying the content's SHA-256 so a later
re-fetch can be compared.

Credentials never reach this layer: adapters pass logical parameters only, and a denylist
strips anything credential-shaped as defence in depth before hashing or writing.
"""

import hashlib
import json
import logging
from collections.abc import Iterator
from datetime import UTC, datetime
from pathlib import Path

from pydantic import Field

from trp.domain.security import FrozenModel
from trp.providers.base import Dataset, RawPayload

logger = logging.getLogger(__name__)

_CREDENTIAL_KEYS = frozenset(
    {
        "api_key",
        "apikey",
        "api_token",
        "apitoken",
        "token",
        "key",
        "secret",
        "password",
        "auth",
        "authorization",
    }
)

_EXTENSIONS = {
    "application/json": "json",
    "text/csv": "csv",
    "text/plain": "txt",
}


class RawRecord(FrozenModel):
    """Sidecar metadata for one stored payload."""

    provider: str = Field(min_length=1)
    provider_version: str = Field(min_length=1)
    dataset: Dataset
    endpoint: str
    params: dict[str, str]
    params_hash: str
    fetched_at: datetime
    content_type: str
    content_sha256: str
    content_bytes: int
    retained: bool


def sanitise_params(params: dict[str, str]) -> dict[str, str]:
    """Drop credential-shaped keys. Defence in depth — adapters must not pass them."""
    return {k: v for k, v in params.items() if k.lower().replace("-", "_") not in _CREDENTIAL_KEYS}


def params_hash(params: dict[str, str]) -> str:
    """Stable hash of logical request parameters, independent of dict ordering."""
    canonical = json.dumps(sanitise_params(params), sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(canonical.encode()).hexdigest()[:16]


class RawStore:
    def __init__(self, root: Path) -> None:
        self._root = root

    def write(
        self,
        provider: str,
        provider_version: str,
        dataset: Dataset,
        payload: RawPayload,
        *,
        fetched_at: datetime | None = None,
        retain: bool = True,
    ) -> Path:
        """Store one payload verbatim; returns the sidecar path (always written).

        Append-only: an existing file is never modified; identical requests get new
        timestamped records.
        """
        fetched = fetched_at if fetched_at is not None else datetime.now(UTC)
        if fetched.tzinfo is None:
            raise ValueError("fetched_at must be timezone-aware (UTC)")

        params = sanitise_params(payload.params)
        digest = params_hash(payload.params)
        directory = self._root / provider / dataset.value / digest
        directory.mkdir(parents=True, exist_ok=True)

        stamp = fetched.astimezone(UTC).strftime("%Y%m%dT%H%M%S.%fZ")
        extension = _EXTENSIONS.get(payload.content_type, "bin")
        sequence = 0
        while True:
            stem = f"{stamp}-{sequence}"
            meta_path = directory / f"{stem}.meta.json"
            content_path = directory / f"{stem}.{extension}"
            if not meta_path.exists() and not content_path.exists():
                break
            sequence += 1

        record = RawRecord(
            provider=provider,
            provider_version=provider_version,
            dataset=dataset,
            endpoint=payload.endpoint,
            params=params,
            params_hash=digest,
            fetched_at=fetched,
            content_type=payload.content_type,
            content_sha256=hashlib.sha256(payload.content).hexdigest(),
            content_bytes=len(payload.content),
            retained=retain,
        )
        if retain:
            content_path.write_bytes(payload.content)
        meta_path.write_text(record.model_dump_json(indent=2))
        logger.debug("raw payload stored: %s (%d bytes)", meta_path, len(payload.content))
        return meta_path

    def read(self, meta_path: Path) -> tuple[RawRecord, bytes | None]:
        """Load a record and its payload bytes (None when not retained)."""
        record = RawRecord.model_validate_json(meta_path.read_text())
        if not record.retained:
            return record, None
        extension = _EXTENSIONS.get(record.content_type, "bin")
        content = meta_path.with_name(meta_path.name.removesuffix(".meta.json") + f".{extension}")
        return record, content.read_bytes()

    def records(
        self, provider: str | None = None, dataset: Dataset | None = None
    ) -> Iterator[Path]:
        """Sidecar paths, filterable by provider and dataset, in sorted (stable) order."""
        providers = [self._root / provider] if provider else sorted(self._root.iterdir())
        for provider_dir in providers:
            if not provider_dir.is_dir():
                continue
            datasets = [provider_dir / dataset.value] if dataset else sorted(provider_dir.iterdir())
            for dataset_dir in datasets:
                if not dataset_dir.is_dir():
                    continue
                yield from sorted(dataset_dir.glob("*/*.meta.json"))
