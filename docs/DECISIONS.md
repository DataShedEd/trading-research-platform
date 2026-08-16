# Decision log

Append-only. Never silently change a decision — supersede it with a new entry that references
the old one.

---

DEC-001
Date: 2026-08-16
Decision: uv for dependency and environment management; Python 3.12 pinned; src layout with package name `trp`.
Context: Greenfield repo; need reproducible environments with minimal ceremony.
Alternatives: Poetry (slower, lock friction), pip-tools (manual), conda (heavyweight).
Reason: uv is fast, handles Python installs and lockfiles in one tool. `trp` avoids stdlib name collisions and is short.
Consequences: Contributors need uv installed. `uv.lock` committed; CI uses `uv sync --locked`.

---

DEC-002
Date: 2026-08-16
Decision: ruff (lint + format), mypy --strict, pytest; GitHub Actions running the identical commands as local `make check`.
Context: Correctness-critical quantitative code needs typing and consistent style with low tool sprawl.
Alternatives: black+flake8+isort trio; pyright.
Reason: ruff subsumes the trio; mypy strict catches the silent-coercion class of bugs the brief forbids. The `DTZ` ruff ruleset mechanically bans naive datetimes.
Consequences: Some verbosity (explicit types everywhere). All timestamps must be tz-aware or code fails lint.

---

DEC-003
Date: 2026-08-16
Decision: DuckDB + Parquet is the only analytical store for Milestone 1; Polars is the primary dataframe library.
Context: Single-user, single-machine research workloads on daily-frequency data for a few thousand securities.
Alternatives: PostgreSQL for everything; SQLite; Pandas-first.
Reason: Columnar Parquet + DuckDB gives fast set-based SQL over versionable files with zero server administration. Polars is typed-friendly, fast, and strict about types (no silent coercion).
Consequences: No concurrent-writer story — acceptable for one researcher. Pandas allowed at notebook edges only.

---

DEC-004
Date: 2026-08-16
Decision: PostgreSQL deferred until a component has genuinely transactional state (experiment registry writes, paper-trading orders); not used in Milestone 1.
Context: Brief prefers Postgres "where useful"; Milestone 1 is batch-analytical only.
Alternatives: Stand up Postgres now.
Reason: Avoid operating a database that would hold nothing. Markdown tickets + Parquet cover all M1 state.
Consequences: Epic 10/15 tickets include introducing Postgres (or consciously choosing SQLite) when reached.

---

DEC-005
Date: 2026-08-16
Decision: Pydantic v2 frozen models for domain records; `Decimal` for prices, dividends, and per-share values in canonical stores; timezone-aware UTC timestamps internally; market-local concepts (trading days, period ends) as `date`.
Context: Need validated, immutable, typed domain objects at system boundaries; float rounding must not corrupt corporate-action arithmetic.
Alternatives: dataclasses (no validation), attrs, floats everywhere.
Reason: Validation at the boundary is where provider data quality problems surface; Decimal makes split/dividend adjustment exact and auditable.
Consequences: Explicit Decimal↔float conversion at the derived-analytics boundary; slight verbosity.

---

DEC-006
Date: 2026-08-16
Decision: One QNT-NNN ticket sequence across all epics; tickets are markdown files in `/tickets` with `INDEX.md` as the human-readable source of truth; one git commit per completed ticket, ticket ID first in the message.
Context: Durable project memory must live in the repository, not chat history.
Alternatives: Per-epic prefixes; external tracker.
Reason: Single sequence keeps IDs stable and grep-able; commits-per-ticket make git history a project journal.
Consequences: Ticket files are updated (status, completion notes) as part of the work they describe.

---

DEC-007
Date: 2026-08-16
Decision: When a provider supplies no announcement timestamp for a fundamental record, impute `available_at` conservatively (late) as period end plus a documented per-market reporting lag, and flag the row as imputed.
Context: Point-in-time correctness requires `available_at`; many providers omit true first-publication timestamps.
Alternatives: Use period end (leaks up to months of future information); drop such rows (destroys coverage).
Reason: A late-biased assumption can only understate strategy performance, never flatter it — the safe direction per QUANT_PRINCIPLES.
Consequences: Backtests on imputed data are conservative; the imputed flag lets us measure sensitivity once a provider with real timestamps is available.

---

DEC-008
Date: 2026-08-16
Decision: Security master records are bitemporal. Event time is a half-open date range (`valid_from` inclusive, `valid_to` exclusive, None = open-ended); knowledge time is `recorded_at`/`superseded_at` (UTC timestamps). Lifecycle changes supersede records rather than replacing them, so every historical knowledge state is reconstructable (`pit.known_as_of`). Downstream consumers use `PointInTimeSecurityMaster`, which requires an explicit `as_of` on every query.
Context: A vendor backfilling a 2014 ticker change in 2026 must not make a 2014 backtest smarter than a 2014 investor. Single-axis event dating cannot express this.
Alternatives: Event-time only with documented limitation; full snapshot copies of the master per ingestion run.
Reason: Supersession preserves knowledge history at row granularity with no snapshot storage cost, and revalidation on every change makes inconsistent states unconstructable. `recorded_at=None` (backfill) treated as always-known is the honest-but-lenient default; fundamentals will use conservative imputation instead (DEC-007) because there the leak direction matters more.
Consequences: Storage carries superseded rows forever (small for the master). Uniqueness invariants apply to current records only. `model_copy(update=...)` is banned on domain records in favour of `revalidated_copy`.

---

DEC-009
Date: 2026-08-16
Decision: Rights-issue price adjustment is deferred. The adjustment engine flags any security with a rights issue in its corporate-action history (computation warning + provenance) instead of adjusting for it.
Context: Correct rights adjustment needs the theoretical ex-rights price, which requires reliable subscription terms and cum-rights prices; provider data quality for historical UK rights issues is unproven until the bake-off runs.
Alternatives: Approximate TERP adjustment now; ignore silently.
Reason: A wrong adjustment is worse than a flagged gap — it produces plausible wrong returns. Flagging keeps affected securities visible so research can exclude or hand-check them.
Consequences: Adjusted series for securities with rights issues are wrong before the issue date until this is revisited (post bake-off, when subscription-terms data quality is known). The warning must be surfaced by QNT-019's validation report and respected by the factor engine.
