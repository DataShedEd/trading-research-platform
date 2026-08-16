from collections.abc import Sequence
from pathlib import Path

import pytest

from tests.fakes.provider import FakeProvider, NoFundamentalsProvider
from trp.bakeoff.checks import Check, Criterion, Finding, Outcome, PayloadPresenceCheck
from trp.bakeoff.harness import RunConfig, RunSummary, entry_symbol, run_bakeoff
from trp.bakeoff.results import FetchStatus, ResultsError, load_run
from trp.bakeoff.universe.loader import (
    AwkwardProperty,
    Market,
    UniverseEntry,
    load_universe,
)
from trp.providers.base import Dataset, ProviderRateLimitError, RawPayload


def page(body: bytes = b'{"rows": [1]}') -> RawPayload:
    return RawPayload(content=body, endpoint="/any", params={"symbol": "X"})


def full_script() -> dict[Dataset, list[RawPayload | Exception]]:
    return {dataset: [page()] for dataset in Dataset}


def config(tmp_path: Path, **overrides: object) -> RunConfig:
    fields: dict[str, object] = {
        "providers": [FakeProvider(full_script())],
        "universe": load_universe(),
        "raw_root": tmp_path / "raw",
        "results_root": tmp_path / "results",
        "run_id": "test-run",
        "checks": [PayloadPresenceCheck()],
    }
    fields.update(overrides)
    return RunConfig(**fields)  # type: ignore[arg-type]


def test_full_matrix_runs_and_persists(tmp_path: Path) -> None:
    universe = load_universe()
    summary = run_bakeoff(config(tmp_path))
    expected_cells = len(universe.entries) * len(Dataset)
    assert summary.cells_completed == expected_cells

    metadata, cells = load_run(summary.run_dir)
    assert metadata.universe_version == universe.version
    assert metadata.providers == {"fake": "0.0-test"}
    assert len(cells) == expected_cells
    # Every OK cell persisted raw payloads before checks, and results reference them.
    for cell in cells:
        if cell.fetch_status is FetchStatus.OK:
            assert cell.raw_refs
            assert all(Path(ref).exists() for ref in cell.raw_refs)
            assert cell.checks
            assert all(c.raw_refs == cell.raw_refs for c in cell.checks)


def test_subset_selection_by_market_property_and_dataset(tmp_path: Path) -> None:
    summary = run_bakeoff(
        config(
            tmp_path,
            datasets=frozenset({Dataset.PRICES}),
            markets=frozenset({Market.UK}),
            properties=frozenset({AwkwardProperty.FAILURE}),
        )
    )
    _, cells = load_run(summary.run_dir)
    assert {c.security_key for c in cells} == {"carillion", "thomas-cook"}
    assert {c.dataset for c in cells} == {Dataset.PRICES}


def test_four_failure_shapes_are_distinguishable(tmp_path: Path) -> None:
    script = full_script()
    script[Dataset.PRICES] = []  # supported but genuinely empty
    provider = NoFundamentalsProvider(script)  # fundamentals unsupported
    summary = run_bakeoff(
        config(
            tmp_path,
            providers=[provider],
            datasets=frozenset({Dataset.PRICES, Dataset.FUNDAMENTALS, Dataset.SECURITIES}),
            markets=frozenset({Market.EU}),  # just SAP: one entry
        )
    )
    _, cells = load_run(summary.run_dir)
    by_dataset = {c.dataset: c for c in cells}
    assert by_dataset[Dataset.PRICES].fetch_status is FetchStatus.EMPTY
    assert by_dataset[Dataset.FUNDAMENTALS].fetch_status is FetchStatus.UNSUPPORTED
    assert by_dataset[Dataset.SECURITIES].fetch_status is FetchStatus.OK
    assert summary.failures.get(FetchStatus.UNSUPPORTED) == 1


def test_rate_limit_backoff_then_gives_up(tmp_path: Path) -> None:
    script = full_script()
    script[Dataset.PRICES] = [ProviderRateLimitError("fake", 7.0)]
    sleeps: list[float] = []
    summary = run_bakeoff(
        config(
            tmp_path,
            providers=[FakeProvider(script)],
            datasets=frozenset({Dataset.PRICES}),
            markets=frozenset({Market.EU}),
            max_rate_limit_retries=2,
            sleep=sleeps.append,
        )
    )
    _, cells = load_run(summary.run_dir)
    assert cells[0].fetch_status is FetchStatus.RATE_LIMITED
    assert cells[0].throttle_events == 3  # initial + 2 retries
    assert sleeps == [7.0, 7.0]  # respected retry_after; gave up after budget


def test_check_exception_is_captured_not_fatal(tmp_path: Path) -> None:
    class Exploding(Check):
        name = "exploding"
        criterion = Criterion.API_RELIABILITY
        datasets = frozenset(Dataset)
        properties = None

        def run(self, entry: UniverseEntry, payloads: Sequence[bytes]) -> list[Finding]:
            raise RuntimeError("check bug")

    summary = run_bakeoff(
        config(
            tmp_path,
            checks=[Exploding()],
            datasets=frozenset({Dataset.PRICES}),
            markets=frozenset({Market.EU}),
        )
    )
    _, cells = load_run(summary.run_dir)
    (result,) = cells[0].checks
    assert result.outcome is Outcome.ERROR
    assert "RuntimeError: check bug" in result.explanation


def test_resume_skips_completed_cells_and_completed_runs_never_overwrite(
    tmp_path: Path,
) -> None:
    first = run_bakeoff(
        config(tmp_path, datasets=frozenset({Dataset.PRICES}), markets=frozenset({Market.EU}))
    )
    assert first.cells_completed == 1

    with pytest.raises(ResultsError, match="never overwritten"):
        run_bakeoff(
            config(tmp_path, datasets=frozenset({Dataset.PRICES}), markets=frozenset({Market.EU}))
        )

    resumed = run_bakeoff(
        config(
            tmp_path,
            datasets=frozenset({Dataset.PRICES}),
            markets=frozenset({Market.EU}),
            resume=True,
        )
    )
    assert resumed.cells_completed == 0
    assert resumed.cells_skipped == 1


def test_replay_uses_stored_payloads_without_refetching(tmp_path: Path) -> None:
    base = config(tmp_path, datasets=frozenset({Dataset.PRICES}), markets=frozenset({Market.EU}))
    run_bakeoff(base)

    # Second run, new id, same raw root: the provider would explode if called again.
    angry_script: dict[Dataset, list[RawPayload | Exception]] = {
        Dataset.PRICES: [ProviderRateLimitError("fake")]
    }
    replayed = run_bakeoff(
        config(
            tmp_path,
            providers=[FakeProvider(angry_script)],
            datasets=frozenset({Dataset.PRICES}),
            markets=frozenset({Market.EU}),
            run_id="second-run",
        )
    )
    _, cells = load_run(replayed.run_dir)
    assert cells[0].fetch_status is FetchStatus.OK
    assert cells[0].replayed is True
    assert cells[0].checks  # checks ran over the stored bytes


def test_entry_symbol_uses_latest_ticker() -> None:
    shell = next(e for e in load_universe().entries if e.key == "shell")
    assert entry_symbol(shell) == "SHEL:XLON"


def test_summary_type_is_informative(tmp_path: Path) -> None:
    summary = run_bakeoff(
        config(tmp_path, datasets=frozenset({Dataset.PRICES}), markets=frozenset({Market.US}))
    )
    assert isinstance(summary, RunSummary)
    assert summary.cells_completed == 3  # apple, citigroup, microsoft
