"""The experiment registry store (QNT-063/066): SQLite, with the workflow enforced.

Storage choice (DEC-022): SQLite via the standard library — records are MUTATED as
conclusions arrive, which rules out Parquet; a single-researcher platform does not yet
justify PostgreSQL's administration (DEC-004's deferral stands until paper trading needs
a shared transactional store). Bulk series stay in Parquet under the run records
(QNT-065); this store holds metadata and references only.

Workflow enforcement (QNT-066) lives HERE, not in the models, because sequence and
counting are properties of the registry, not of any one record:
- an experiment can only be created against an existing hypothesis, so the hypothesis
  timestamp always precedes it; CONFIRMATORY classification additionally requires the
  hypothesis to predate the experiment record itself.
- transitions follow ``ALLOWED_TRANSITIONS`` exactly; abandonment requires a reason;
  nothing is ever deleted.
- the variant count per hypothesis includes every experiment — abandoned ones included —
  and is stamped into every conclusion; past ``VARIANT_WARNING_THRESHOLD`` variants with
  no out-of-sample run on record, the conclusion carries a multiple-testing warning that
  can only be cleared by recording such a run (an experiment tagged ``out-of-sample``).
- a run recorded from a dirty working tree is stored as non-reproducible and cannot be
  cited as the evidence for a CONFIRMATORY conclusion.
"""

import json
import sqlite3
from datetime import UTC, datetime
from pathlib import Path

from pydantic import ValidationError

from trp.experiments.records import (
    ALLOWED_TRANSITIONS,
    SCHEMA_VERSION,
    VARIANT_WARNING_THRESHOLD,
    Classification,
    Conclusion,
    Experiment,
    ExperimentStatus,
    Hypothesis,
)

OUT_OF_SAMPLE_TAG = "out-of-sample"


class RegistryError(Exception):
    pass


_DDL = """
CREATE TABLE IF NOT EXISTS hypotheses (
    hypothesis_id TEXT PRIMARY KEY,
    created_at TEXT NOT NULL,
    payload TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS experiments (
    experiment_id TEXT PRIMARY KEY,
    hypothesis_id TEXT NOT NULL REFERENCES hypotheses(hypothesis_id),
    name TEXT NOT NULL,
    status TEXT NOT NULL,
    classification TEXT NOT NULL,
    created_at TEXT NOT NULL,
    payload TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS runs (
    run_id TEXT PRIMARY KEY,
    experiment_id TEXT NOT NULL REFERENCES experiments(experiment_id),
    started_at TEXT NOT NULL,
    reproducible INTEGER NOT NULL,
    manifest TEXT NOT NULL,
    metrics TEXT,
    artefact_path TEXT
);
"""


class Registry:
    def __init__(self, path: Path) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        self._connection = sqlite3.connect(path)
        self._connection.execute("PRAGMA foreign_keys = ON")
        version = self._connection.execute("PRAGMA user_version").fetchone()[0]
        if version == 0:
            self._connection.executescript(_DDL)
            self._connection.execute(f"PRAGMA user_version = {SCHEMA_VERSION}")
            self._connection.commit()
        elif version != SCHEMA_VERSION:
            raise RegistryError(
                f"registry schema v{version} on disk, code expects v{SCHEMA_VERSION}: "
                "migrate deliberately before touching it"
            )

    # ------------------------------------------------------------------ hypotheses
    def add_hypothesis(self, hypothesis: Hypothesis) -> None:
        self._connection.execute(
            "INSERT INTO hypotheses VALUES (?, ?, ?)",
            (
                hypothesis.hypothesis_id,
                hypothesis.created_at.isoformat(),
                hypothesis.model_dump_json(),
            ),
        )
        self._connection.commit()

    def hypothesis(self, hypothesis_id: str) -> Hypothesis:
        row = self._connection.execute(
            "SELECT payload FROM hypotheses WHERE hypothesis_id = ?", (hypothesis_id,)
        ).fetchone()
        if row is None:
            raise RegistryError(f"no hypothesis {hypothesis_id}")
        try:
            return Hypothesis.model_validate_json(row[0])
        except ValidationError as error:
            raise RegistryError(
                f"{hypothesis_id}: stored record does not validate — likely written by a "
                f"newer schema; refusing to guess ({error})"
            ) from error

    # ----------------------------------------------------------------- experiments
    def add_experiment(self, experiment: Experiment) -> None:
        hypothesis = self.hypothesis(experiment.hypothesis_id)  # existence is mandatory
        if (
            experiment.classification is Classification.CONFIRMATORY
            and hypothesis.created_at >= experiment.created_at
        ):
            raise RegistryError(
                "an experiment whose hypothesis was written afterwards is exploratory "
                "by definition and cannot be classified confirmatory"
            )
        if experiment.status is not ExperimentStatus.DESIGNED:
            raise RegistryError("experiments enter the registry as DESIGNED")
        self._write_experiment(experiment, insert=True)

    def experiment(self, experiment_id: str) -> Experiment:
        row = self._connection.execute(
            "SELECT payload FROM experiments WHERE experiment_id = ?", (experiment_id,)
        ).fetchone()
        if row is None:
            raise RegistryError(f"no experiment {experiment_id}")
        try:
            return Experiment.model_validate_json(row[0])
        except ValidationError as error:
            raise RegistryError(
                f"{experiment_id}: stored record does not validate — likely written by a "
                f"newer schema; refusing to guess ({error})"
            ) from error

    def _write_experiment(self, experiment: Experiment, *, insert: bool = False) -> None:
        values = (
            experiment.experiment_id,
            experiment.hypothesis_id,
            experiment.name,
            experiment.status.value,
            experiment.classification.value,
            experiment.created_at.isoformat(),
            experiment.model_dump_json(),
        )
        if insert:
            self._connection.execute("INSERT INTO experiments VALUES (?, ?, ?, ?, ?, ?, ?)", values)
        else:
            self._connection.execute(
                "UPDATE experiments SET hypothesis_id=?, name=?, status=?, "
                "classification=?, created_at=?, payload=? WHERE experiment_id=?",
                (*values[1:], experiment.experiment_id),
            )
        self._connection.commit()

    def _transition(self, experiment: Experiment, updated: Experiment) -> None:
        allowed = ALLOWED_TRANSITIONS[experiment.status]
        if updated.status not in allowed:
            raise RegistryError(
                f"{experiment.experiment_id}: {experiment.status.value} -> "
                f"{updated.status.value} is not a legal transition "
                f"(allowed: {sorted(s.value for s in allowed)})"
            )
        self._write_experiment(updated)

    def start(self, experiment_id: str, *, at: datetime | None = None) -> Experiment:
        experiment = self.experiment(experiment_id)
        updated = _evolve(experiment, status=ExperimentStatus.RUNNING, started_at=at or _now())
        self._transition(experiment, updated)
        return updated

    def complete(self, experiment_id: str, *, at: datetime | None = None) -> Experiment:
        experiment = self.experiment(experiment_id)
        updated = _evolve(experiment, status=ExperimentStatus.COMPLETED, completed_at=at or _now())
        self._transition(experiment, updated)
        return updated

    def abandon(self, experiment_id: str, reason: str) -> Experiment:
        if not reason.strip():
            raise RegistryError("abandonment requires a reason")
        experiment = self.experiment(experiment_id)
        updated = _evolve(experiment, status=ExperimentStatus.ABANDONED, abandoned_reason=reason)
        self._transition(experiment, updated)
        return updated

    def conclude(self, experiment_id: str, conclusion: Conclusion) -> Experiment:
        experiment = self.experiment(experiment_id)
        run = self._run_row(conclusion.evidence_run_id)
        if run is None:
            raise RegistryError(
                f"conclusion cites run {conclusion.evidence_run_id!r} which is not on record"
            )
        run_experiment_id, reproducible = run
        if run_experiment_id != experiment_id:
            raise RegistryError("the cited evidence run belongs to a different experiment")
        if experiment.classification is Classification.CONFIRMATORY and not reproducible:
            raise RegistryError(
                "a non-reproducible run (dirty working tree) cannot be evidence for a "
                "confirmatory conclusion"
            )
        variants = self.variant_count(experiment.hypothesis_id)
        warning = conclusion.multiple_testing_warning
        if variants > VARIANT_WARNING_THRESHOLD and not self._has_out_of_sample(
            experiment.hypothesis_id
        ):
            warning = (
                f"{variants} variants tried against this hypothesis with no "
                f"out-of-sample run on record (threshold {VARIANT_WARNING_THRESHOLD}); "
                "record an experiment tagged "
                f"'{OUT_OF_SAMPLE_TAG}' to clear this"
            )
        stamped = conclusion.model_copy(update={"multiple_testing_warning": warning})
        updated = _evolve(experiment, status=ExperimentStatus.CONCLUDED, conclusion=stamped)
        self._transition(experiment, updated)
        return updated

    # ------------------------------------------------------------------------ runs
    def record_run(
        self,
        run_id: str,
        experiment_id: str,
        *,
        manifest: dict[str, object],
        reproducible: bool,
        metrics: dict[str, object] | None = None,
        artefact_path: str | None = None,
        started_at: datetime | None = None,
    ) -> None:
        self.experiment(experiment_id)  # must exist
        self._connection.execute(
            "INSERT INTO runs VALUES (?, ?, ?, ?, ?, ?, ?)",
            (
                run_id,
                experiment_id,
                (started_at or _now()).isoformat(),
                1 if reproducible else 0,
                json.dumps(manifest, sort_keys=True),
                json.dumps(metrics, sort_keys=True) if metrics is not None else None,
                artefact_path,
            ),
        )
        self._connection.commit()

    def _run_row(self, run_id: str) -> tuple[str, bool] | None:
        row = self._connection.execute(
            "SELECT experiment_id, reproducible FROM runs WHERE run_id = ?", (run_id,)
        ).fetchone()
        return None if row is None else (row[0], bool(row[1]))

    def run(self, run_id: str) -> dict[str, object]:
        row = self._connection.execute(
            "SELECT run_id, experiment_id, started_at, reproducible, manifest, metrics, "
            "artefact_path FROM runs WHERE run_id = ?",
            (run_id,),
        ).fetchone()
        if row is None:
            raise RegistryError(f"no run {run_id}")
        return {
            "run_id": row[0],
            "experiment_id": row[1],
            "started_at": row[2],
            "reproducible": bool(row[3]),
            "manifest": json.loads(row[4]),
            "metrics": json.loads(row[5]) if row[5] else None,
            "artefact_path": row[6],
        }

    # -------------------------------------------------------------------- counting
    def variant_count(self, hypothesis_id: str) -> int:
        """Every experiment ever run against the hypothesis — abandoned ones included."""
        return int(
            self._connection.execute(
                "SELECT count(*) FROM experiments WHERE hypothesis_id = ?", (hypothesis_id,)
            ).fetchone()[0]
        )

    def _has_out_of_sample(self, hypothesis_id: str) -> bool:
        rows = self._connection.execute(
            "SELECT payload FROM experiments WHERE hypothesis_id = ?", (hypothesis_id,)
        ).fetchall()
        for (payload,) in rows:
            if OUT_OF_SAMPLE_TAG in Experiment.model_validate_json(payload).tags:
                return True
        return False


def _evolve(experiment: Experiment, **updates: object) -> Experiment:
    return Experiment.model_validate({**experiment.model_dump(), **updates})


def _now() -> datetime:
    return datetime.now(UTC)
