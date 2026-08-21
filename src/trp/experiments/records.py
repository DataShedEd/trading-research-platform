"""Experiment registry records (QNT-063): the four artefacts as executable schema.

RESEARCH_METHODOLOGY's discipline, made structurally mandatory: a hypothesis is written
BEFORE an experiment (its own record, its own timestamp); an experiment names everything
that determines reproducibility at creation time (universe, periods, factor versions,
costs, benchmark — all carried by the embedded ``BacktestConfig``); evidence is a run
reference, never a pasted number; a conclusion cannot exist without a judgement, a cited
evidence run and at least one weakness. Failed and abandoned experiments are kept
forever — they are the denominator.

Statuses: DESIGNED -> RUNNING -> COMPLETED -> CONCLUDED, with ABANDONED reachable from
any pre-concluded state and requiring a reason. Transitions live in the store (QNT-066
enforces sequence and counting); these models enforce shape.

Schema versioning: every record carries ``schema_version``; readers reject unknown
fields loudly (``extra="forbid"``) rather than dropping what a future version wrote.
"""

from datetime import UTC, datetime
from enum import StrEnum
from typing import Self
from uuid import uuid4

from pydantic import BaseModel, ConfigDict, Field, model_validator

from trp.backtest.config import BacktestConfig

SCHEMA_VERSION = 1

VARIANT_WARNING_THRESHOLD = 5
"""Documented convention (rule 3): more variants than this without an out-of-sample run
marks any conclusion with a multiple-testing warning. A number to argue with, not a
statistical claim."""


class RegistryModel(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")


class ExperimentStatus(StrEnum):
    DESIGNED = "designed"
    RUNNING = "running"
    COMPLETED = "completed"
    CONCLUDED = "concluded"
    ABANDONED = "abandoned"


ALLOWED_TRANSITIONS: dict[ExperimentStatus, frozenset[ExperimentStatus]] = {
    ExperimentStatus.DESIGNED: frozenset({ExperimentStatus.RUNNING, ExperimentStatus.ABANDONED}),
    ExperimentStatus.RUNNING: frozenset({ExperimentStatus.COMPLETED, ExperimentStatus.ABANDONED}),
    ExperimentStatus.COMPLETED: frozenset(
        {ExperimentStatus.CONCLUDED, ExperimentStatus.RUNNING, ExperimentStatus.ABANDONED}
    ),
    ExperimentStatus.CONCLUDED: frozenset(),
    ExperimentStatus.ABANDONED: frozenset(),
}


class Classification(StrEnum):
    CONFIRMATORY = "confirmatory"
    EXPLORATORY = "exploratory"


class Judgement(StrEnum):
    SUPPORTED = "supported"
    NOT_SUPPORTED = "not_supported"
    INCONCLUSIVE = "inconclusive"


def _now() -> datetime:
    return datetime.now(UTC)


def new_hypothesis_id() -> str:
    return f"HYP-{uuid4()}"


def new_experiment_id() -> str:
    return f"EXP-{uuid4()}"


class Hypothesis(RegistryModel):
    """A falsifiable statement, written down before anything runs."""

    schema_version: int = SCHEMA_VERSION
    hypothesis_id: str = Field(pattern=r"^HYP-[0-9a-f-]{36}$")
    statement: str = Field(min_length=20, description="falsifiable, specific")
    rationale: str = Field(min_length=1)
    created_at: datetime

    @model_validator(mode="after")
    def _aware(self) -> Self:
        if self.created_at.tzinfo is None:
            raise ValueError("created_at must be timezone-aware")
        return self


class Conclusion(RegistryModel):
    """An explicit judgement citing evidence, with its weaknesses on record."""

    judgement: Judgement
    text: str = Field(min_length=20)
    evidence_run_id: str = Field(min_length=1, description="the run whose numbers are cited")
    weaknesses: tuple[str, ...] = Field(min_length=1)
    follow_ups: tuple[str, ...] = ()
    parameter_sensitivity: str | None = Field(
        default=None,
        description="rule 4: where a parameter was searched, the ±50% perturbation result",
    )
    multiple_testing_warning: str | None = None
    concluded_at: datetime


class Experiment(RegistryModel):
    """One concrete parameterisation of a hypothesis.

    The embedded ``BacktestConfig`` carries universe, periods, factor name+version,
    construction rules, cost assumptions and benchmark — the reproducibility-determining
    fields the methodology requires — so an experiment cannot be created without them."""

    schema_version: int = SCHEMA_VERSION
    experiment_id: str = Field(pattern=r"^EXP-[0-9a-f-]{36}$")
    hypothesis_id: str = Field(pattern=r"^HYP-[0-9a-f-]{36}$")
    name: str = Field(pattern=r"^[a-z0-9-]+$")
    rationale: str = Field(min_length=1, description="why THIS parameterisation")
    config: BacktestConfig
    classification: Classification
    tags: tuple[str, ...] = ()
    status: ExperimentStatus = ExperimentStatus.DESIGNED
    created_at: datetime
    started_at: datetime | None = None
    completed_at: datetime | None = None
    conclusion: Conclusion | None = None
    abandoned_reason: str | None = None

    @model_validator(mode="after")
    def _status_shape(self) -> Self:
        if (self.status is ExperimentStatus.CONCLUDED) != (self.conclusion is not None):
            raise ValueError("CONCLUDED and a Conclusion imply each other")
        if (self.status is ExperimentStatus.ABANDONED) != (self.abandoned_reason is not None):
            raise ValueError("ABANDONED requires (and is required by) a reason")
        needs_start = self.status in (ExperimentStatus.RUNNING, ExperimentStatus.COMPLETED)
        if needs_start and self.started_at is None:
            raise ValueError(f"{self.status} requires started_at")
        if self.status is ExperimentStatus.COMPLETED and self.completed_at is None:
            raise ValueError("COMPLETED requires completed_at")
        return self
