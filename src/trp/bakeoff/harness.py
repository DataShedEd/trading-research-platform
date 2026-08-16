"""The bake-off runner: (provider x validation security x dataset kind) -> evidence.

For every cell the runner fetches through the common provider interface, persists the raw
payload FIRST (a failed check must be adjudicable months later, after a subscription may
have lapsed), then runs every applicable registered check, then appends one cell record
to the run's results. A failing check never aborts the run; an exception inside a check
becomes an ``error`` result carrying its traceback.

Replay: when the raw store already holds payloads for a cell's exact request, they are
used instead of the network (the default) — re-running checks costs no API quota.

Rate limits: fetches back off on ``ProviderRateLimitError`` (respecting ``retry_after``)
up to a retry budget; throttling events are recorded per cell because API reliability is
itself a scored criterion. Runs are resumable: completed cells are skipped, so a day-cap
exhaustion pauses a run rather than voiding it.

Symbols: the harness addresses securities as ``TICKER:MIC`` (latest known ticker from the
universe entry); adapters translate to their provider's native symbology.
"""

import logging
import time
import traceback
from collections.abc import Callable, Iterable, Sequence
from dataclasses import dataclass, field
from datetime import UTC, date, datetime
from pathlib import Path

from trp.bakeoff.checks import Check, CheckResult, Finding, Outcome, registered_checks
from trp.bakeoff.results import (
    CellRecord,
    FetchStatus,
    RunMetadata,
    append_cell,
    completed_cells,
    create_run,
)
from trp.bakeoff.universe.loader import (
    AwkwardProperty,
    Market,
    UniverseEntry,
    ValidationUniverse,
)
from trp.domain.security import revalidated_copy
from trp.ingestion.raw import RawStore, params_hash
from trp.providers.base import (
    Dataset,
    MarketDataProvider,
    ProviderCapabilityError,
    ProviderError,
    ProviderRateLimitError,
    RawPayload,
)

logger = logging.getLogger(__name__)

_HISTORY_START = date(1990, 1, 1)


@dataclass(frozen=True)
class RunConfig:
    providers: Sequence[MarketDataProvider]
    universe: ValidationUniverse
    raw_root: Path
    results_root: Path
    run_id: str
    datasets: frozenset[Dataset] = frozenset(Dataset)
    markets: frozenset[Market] | None = None
    properties: frozenset[AwkwardProperty] | None = None
    resume: bool = False
    max_rate_limit_retries: int = 3
    checks: Sequence[Check] | None = None  # None = the global registry
    sleep: Callable[[float], None] = time.sleep  # injectable for tests
    history_end: date | None = None  # None = today


@dataclass
class RunSummary:
    run_dir: Path
    cells_completed: int = 0
    cells_skipped: int = 0
    throttle_events: int = 0
    failures: dict[FetchStatus, int] = field(default_factory=dict)


def entry_symbol(entry: UniverseEntry) -> str:
    tickers = [i for i in entry.identifiers if i.kind == "ticker" and i.value is not None]
    if not tickers:
        raise ValueError(f"universe entry {entry.key} has no usable ticker")
    latest = max(tickers, key=lambda t: (t.valid_to is None, t.valid_from or date.min))
    assert latest.value is not None
    return f"{latest.value}:{latest.mic}"


def _selected_entries(config: RunConfig) -> list[UniverseEntry]:
    entries = list(config.universe.entries)
    if config.markets is not None:
        entries = [e for e in entries if e.market in config.markets]
    if config.properties is not None:
        entries = [e for e in entries if config.properties & set(e.properties)]
    return entries


def _cell_params(dataset: Dataset, symbol: str, end: date) -> dict[str, str]:
    params = {"symbol": symbol}
    if dataset in (Dataset.PRICES, Dataset.CORPORATE_ACTIONS):
        params |= {"from": _HISTORY_START.isoformat(), "to": end.isoformat()}
    return params


def _fetch(
    provider: MarketDataProvider,
    dataset: Dataset,
    symbol: str,
    end: date,
    config: RunConfig,
) -> tuple[FetchStatus, list[RawPayload], int]:
    """One cell's fetch with rate-limit backoff. Returns (status, pages, throttles)."""
    throttles = 0
    attempts = 0
    while True:
        try:
            pages = list(_call(provider, dataset, symbol, end))
            return (FetchStatus.OK if pages else FetchStatus.EMPTY), pages, throttles
        except ProviderCapabilityError:
            return FetchStatus.UNSUPPORTED, [], throttles
        except ProviderRateLimitError as exc:
            throttles += 1
            attempts += 1
            if attempts > config.max_rate_limit_retries:
                return FetchStatus.RATE_LIMITED, [], throttles
            config.sleep(exc.retry_after_seconds or 30.0)
        except ProviderError:
            logger.warning("provider error on %s %s %s", provider.name, dataset, symbol)
            return FetchStatus.PROVIDER_ERROR, [], throttles


def _call(
    provider: MarketDataProvider, dataset: Dataset, symbol: str, end: date
) -> Iterable[RawPayload]:
    match dataset:
        case Dataset.SECURITIES:
            return provider.securities()
        case Dataset.PRICES:
            return provider.prices(symbol, _HISTORY_START, end)
        case Dataset.CORPORATE_ACTIONS:
            return provider.corporate_actions(symbol, _HISTORY_START, end)
        case Dataset.FUNDAMENTALS:
            return provider.fundamentals(symbol)
        case Dataset.FINANCIAL_PERIODS:
            return provider.financial_periods(symbol)
        case Dataset.DELISTED_SECURITIES:
            return provider.delisted_securities()


def _replay_payloads(
    store: RawStore, provider: str, dataset: Dataset, params: dict[str, str]
) -> tuple[list[bytes], list[str]]:
    digest = params_hash(params)
    contents: list[bytes] = []
    refs: list[str] = []
    for meta_path in store.records(provider=provider, dataset=dataset):
        if meta_path.parent.name != digest:
            continue
        _record, payload = store.read(meta_path)
        if payload is not None:
            contents.append(payload)
            refs.append(str(meta_path))
    return contents, refs


def _run_checks(
    checks: Sequence[Check],
    entry: UniverseEntry,
    dataset: Dataset,
    provider: str,
    payloads: list[bytes],
    raw_refs: tuple[str, ...],
) -> tuple[CheckResult, ...]:
    results: list[CheckResult] = []
    for check in checks:
        if not check.applies_to(entry, dataset):
            continue
        try:
            findings = check.run(entry, payloads)
        except Exception:
            findings = [
                Finding(
                    outcome=Outcome.ERROR,
                    explanation="check raised:\n" + traceback.format_exc(),
                )
            ]
        results.extend(
            CheckResult(
                check=check.name,
                criterion=check.criterion,
                provider=provider,
                security_key=entry.key,
                dataset=dataset,
                outcome=f.outcome,
                expected=f.expected,
                observed=f.observed,
                explanation=f.explanation,
                raw_refs=raw_refs,
            )
            for f in findings
        )
    return tuple(results)


def run_bakeoff(config: RunConfig) -> RunSummary:
    metadata = RunMetadata(
        run_id=config.run_id,
        universe_version=config.universe.version,
        providers={p.name: p.version for p in config.providers},
        started_at=datetime.now(UTC),
        filters={
            "datasets": sorted(d.value for d in config.datasets),
            "markets": sorted(m.value for m in (config.markets or [])),
            "properties": sorted(p.value for p in (config.properties or [])),
        },
    )
    run_dir = create_run(config.results_root, metadata, resume=config.resume)
    done = completed_cells(run_dir) if config.resume else set()
    store = RawStore(config.raw_root)
    checks = tuple(config.checks) if config.checks is not None else registered_checks()
    end = config.history_end or datetime.now(UTC).date()

    summary = RunSummary(run_dir=run_dir)
    for provider in config.providers:
        for entry in _selected_entries(config):
            symbol = entry_symbol(entry)
            for dataset in sorted(config.datasets):
                if (provider.name, entry.key, dataset.value) in done:
                    summary.cells_skipped += 1
                    continue
                params = _cell_params(dataset, symbol, end)

                payload_bytes, refs = _replay_payloads(store, provider.name, dataset, params)
                replayed = bool(payload_bytes)
                throttles = 0
                if replayed:
                    status = FetchStatus.OK
                else:
                    status, pages, throttles = _fetch(provider, dataset, symbol, end, config)
                    for page in pages:  # raw persists BEFORE any check runs
                        # Stamp the harness's canonical request params so replay can
                        # find the payload by the same identity that produced it.
                        canonical = revalidated_copy(page, params=params)
                        refs.append(
                            str(store.write(provider.name, provider.version, dataset, canonical))
                        )
                        payload_bytes.append(page.content)

                check_results = (
                    _run_checks(checks, entry, dataset, provider.name, payload_bytes, tuple(refs))
                    if status in (FetchStatus.OK, FetchStatus.EMPTY)
                    else ()
                )
                append_cell(
                    run_dir,
                    CellRecord(
                        provider=provider.name,
                        security_key=entry.key,
                        dataset=dataset,
                        fetch_status=status,
                        throttle_events=throttles,
                        replayed=replayed,
                        raw_refs=tuple(refs),
                        checks=check_results,
                        completed_at=datetime.now(UTC),
                    ),
                )
                summary.cells_completed += 1
                summary.throttle_events += throttles
                if status not in (FetchStatus.OK, FetchStatus.EMPTY):
                    summary.failures[status] = summary.failures.get(status, 0) + 1
    return summary
