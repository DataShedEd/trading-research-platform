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
