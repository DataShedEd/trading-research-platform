from datetime import UTC, date, datetime
from pathlib import Path

import pytest

from tests.fakes.provider import FakeProvider
from trp.ingestion.raw import RawStore, params_hash, sanitise_params
from trp.providers.base import Dataset, RawPayload

FETCHED = datetime(2026, 8, 16, 9, 30, tzinfo=UTC)
SECRET = "sk-VERY-SECRET-VALUE-12345"

WEIRD_BYTES = b'{"unsorted":2,"a":1}\n\xc2\xa3trailing-non-json'


def payload(content: bytes = WEIRD_BYTES) -> RawPayload:
    return RawPayload(
        content=content, endpoint="/eod/TST.LSE", params={"symbol": "TST", "from": "2020-01-01"}
    )


def test_payload_bytes_are_verbatim(tmp_path: Path) -> None:
    store = RawStore(tmp_path)
    meta = store.write("fake", "0.0", Dataset.PRICES, payload(), fetched_at=FETCHED)
    record, content = store.read(meta)
    assert content == WEIRD_BYTES  # byte-for-byte: no reformatting, reordering, coercion
    assert record.content_bytes == len(WEIRD_BYTES)
    assert record.fetched_at == FETCHED
    assert record.fetched_at.tzinfo is not None


def test_append_only_never_modifies_existing_files(tmp_path: Path) -> None:
    store = RawStore(tmp_path)
    first = store.write("fake", "0.0", Dataset.PRICES, payload(), fetched_at=FETCHED)
    snapshot = {p: p.read_bytes() for p in tmp_path.rglob("*") if p.is_file()}

    # Identical request, identical timestamp: appends a new record, touches nothing.
    second = store.write("fake", "0.0", Dataset.PRICES, payload(b"different"), fetched_at=FETCHED)
    assert second != first
    for path, content in snapshot.items():
        assert path.read_bytes() == content
    assert not hasattr(store, "delete")


def test_params_hash_is_order_independent_and_secret_free() -> None:
    a = params_hash({"symbol": "TST", "from": "2020-01-01"})
    b = params_hash({"from": "2020-01-01", "symbol": "TST"})
    assert a == b
    # Credential-shaped keys do not participate in identity.
    assert params_hash({"symbol": "TST", "from": "2020-01-01", "api_key": SECRET}) == a
    assert sanitise_params({"api_token": SECRET, "symbol": "TST"}) == {"symbol": "TST"}


def test_secrets_never_reach_disk(tmp_path: Path) -> None:
    store = RawStore(tmp_path)
    dirty = RawPayload(
        content=b'{"rows": []}',
        endpoint="/eod/TST.LSE",
        params={"symbol": "TST", "api_key": SECRET, "Authorization": SECRET},
    )
    store.write("fake", "0.0", Dataset.PRICES, dirty, fetched_at=FETCHED)
    for path in tmp_path.rglob("*"):
        if path.is_file():
            assert SECRET.encode() not in path.read_bytes(), path


def test_naive_fetch_timestamp_rejected(tmp_path: Path) -> None:
    store = RawStore(tmp_path)
    with pytest.raises(ValueError, match="timezone-aware"):
        store.write(
            "fake",
            "0.0",
            Dataset.PRICES,
            payload(),
            fetched_at=datetime(2026, 8, 16, 9, 30),  # noqa: DTZ001 — the point of the test
        )


def test_retention_policy_stores_metadata_only(tmp_path: Path) -> None:
    store = RawStore(tmp_path)
    meta = store.write(
        "restrictive", "0.0", Dataset.FUNDAMENTALS, payload(), fetched_at=FETCHED, retain=False
    )
    record, content = store.read(meta)
    assert content is None
    assert record.retained is False
    assert record.content_sha256  # comparable against a future re-fetch
    stored = [p for p in tmp_path.rglob("*") if p.is_file()]
    assert stored == [meta]  # sidecar only, no payload file


def test_full_ingestion_path_against_fake_provider(tmp_path: Path) -> None:
    pages = [
        RawPayload(content=b'{"page":1}', endpoint="/eod/TST.LSE", params={"symbol": "TST"}),
        RawPayload(content=b'{"page":2}', endpoint="/eod/TST.LSE", params={"symbol": "TST"}),
    ]
    provider = FakeProvider({Dataset.PRICES: list(pages)})
    store = RawStore(tmp_path)
    for page in provider.prices("TST", date(2020, 1, 1), date(2020, 12, 31)):
        store.write(provider.name, provider.version, Dataset.PRICES, page, fetched_at=FETCHED)

    metas = list(store.records(provider="fake", dataset=Dataset.PRICES))
    assert len(metas) == 2
    contents = {store.read(m)[1] for m in metas}
    assert contents == {b'{"page":1}', b'{"page":2}'}
    assert list(store.records(provider="fake", dataset=Dataset.FUNDAMENTALS)) == []
