"""Structured, append-only persistence of bake-off runs under a results root.

One directory per run identifier:

    <root>/<run_id>/metadata.json    # written once at creation; refuses overwrite
    <root>/<run_id>/cells.jsonl      # one line per completed (provider, security, dataset)

JSONL is the store of record — inspectable, diffable, resumable (a crashed run continues
by skipping cells already present). The report generator (QNT-036) reads it via
:func:`load_run`. Completed runs are never overwritten; re-running is a new run id.
"""

from datetime import UTC, datetime
from enum import StrEnum
from pathlib import Path

from pydantic import Field

from trp.bakeoff.checks import CheckResult
from trp.domain.security import FrozenModel
from trp.providers.base import Dataset


class FetchStatus(StrEnum):
    """The four distinguishable non-success shapes plus success (QNT-029 criterion)."""

    OK = "ok"
    EMPTY = "empty"  # supported, responded, genuinely no data
    UNSUPPORTED = "unsupported"  # ProviderCapabilityError: the tier/API has no such dataset
    RATE_LIMITED = "rate_limited"  # throttled beyond retries
    PROVIDER_ERROR = "provider_error"  # transport/5xx after retries


class RunMetadata(FrozenModel):
    run_id: str = Field(pattern=r"^[a-z0-9-]+$")
    universe_version: str
    providers: dict[str, str]  # name -> adapter version
    started_at: datetime
    filters: dict[str, list[str]] = Field(default_factory=dict)


class CellRecord(FrozenModel):
    provider: str
    security_key: str
    dataset: Dataset
    fetch_status: FetchStatus
    throttle_events: int = 0
    replayed: bool = False
    raw_refs: tuple[str, ...] = ()
    checks: tuple[CheckResult, ...] = ()
    completed_at: datetime

    def cell_key(self) -> tuple[str, str, str]:
        return (self.provider, self.security_key, self.dataset.value)


class ResultsError(Exception):
    pass


def create_run(root: Path, metadata: RunMetadata, *, resume: bool = False) -> Path:
    directory = root / metadata.run_id
    if directory.exists() and not resume:
        raise ResultsError(
            f"run {metadata.run_id!r} already exists; runs are never overwritten — "
            "use a new run id, or resume=True to continue an interrupted run"
        )
    directory.mkdir(parents=True, exist_ok=True)
    meta_path = directory / "metadata.json"
    if not meta_path.exists():
        meta_path.write_text(metadata.model_dump_json(indent=2))
    return directory


def append_cell(run_dir: Path, cell: CellRecord) -> None:
    with (run_dir / "cells.jsonl").open("a") as handle:
        handle.write(cell.model_dump_json() + "\n")


def completed_cells(run_dir: Path) -> set[tuple[str, str, str]]:
    path = run_dir / "cells.jsonl"
    if not path.exists():
        return set()
    return {
        CellRecord.model_validate_json(line).cell_key()
        for line in path.read_text().splitlines()
        if line.strip()
    }


def load_run(run_dir: Path) -> tuple[RunMetadata, list[CellRecord]]:
    metadata = RunMetadata.model_validate_json((run_dir / "metadata.json").read_text())
    cells_path = run_dir / "cells.jsonl"
    cells = (
        [
            CellRecord.model_validate_json(line)
            for line in cells_path.read_text().splitlines()
            if line.strip()
        ]
        if cells_path.exists()
        else []
    )
    return metadata, cells


def now_utc() -> datetime:
    return datetime.now(UTC)
