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

---

DEC-010
Date: 2026-08-16
Decision: Trading calendars come from the `exchange-calendars` library, wrapped by `trp.canonical.calendars`, with a fixed supported range per exchange (2000-01-01 to 2030-12-31 for XLON, XNYS, XNAS) and no committed snapshot for now. The wrapper is the only code allowed to import the library.
Context: QNT-016 needs LSE, NYSE and Nasdaq trading days, holidays and half days. The alternative is curating holiday data files ourselves.
Alternatives: Curated committed data files (stable and auditable, but substantial ongoing work and our own errors to find); the library snapshotted to committed files and treated as canonical (the ticket's suggested middle path).
Reason: The library is mature, actively maintained, and its LSE coverage — including the irregular bank holidays that weekday logic gets wrong — is better than anything we would hand-curate soon. Snapshotting is deferred rather than rejected: it is worth doing once the price bake-off has reconciled calendar days against observed price dates (QNT-019), because a snapshot taken before that reconciliation would just freeze unverified data.
Consequences: Historical holiday data can change between library versions, which would silently change past backtest results and violate reproducibility (QUANT_PRINCIPLES §4). Three things bound that risk: the version is pinned in `uv.lock`, so a change only arrives with a deliberate dependency update; `tests/canonical/test_calendars.py` asserts hand-derived expected values (holidays, half days, session counts) so a changed historical calendar fails tests rather than passing silently; and the supported range is fixed in code rather than anchored to today, so the same historical query is answerable identically in any year. Offline reproducibility is otherwise fine — the library computes calendars locally with no network access. If QNT-019 finds discrepancies against observed price dates, curated overrides can be layered on top of the wrapper, or the snapshot approach adopted, without changing any caller.

---

DEC-011
Date: 2026-08-16
Decision: Canonical fundamentals are stored as Parquet partitioned by period-end year only (`data/canonical/fundamentals/period_year=YYYY/part-N.parquet`), with values as Parquet Decimal(38, 6). Writers append new part-files, never rewrite existing ones; the stable row key is (security, statement, line item, period end, period type, revision sequence).
Context: The dataset is long and narrow, queried as a few line items across many securities filtered by availability. Partitioning by security would produce tens of thousands of tiny files; no partitioning would force full scans for period-bounded queries.
Alternatives: Partition by security (file explosion); by statement+year (more dirs for little pruning benefit at this width); no partitioning.
Reason: A universe-year of statements is tens of thousands of rows — one comfortable file per year (validated by a synthetic-volume test: 900 rows across 3 years produce exactly 3 files). Decimal(38,6) spans per-share pence to trillion-scale balance-sheet lines with six decimal places; out-of-range errors rather than truncating.
Consequences: Changing either choice later means rewriting the dataset (always possible from immutable raw payloads, but expensive). Append-only part-files mean deletion/compaction is a deliberate future operation, never implicit.

---

DEC-012
Date: 2026-08-16
Decision: The bake-off rubric includes veto thresholds: a provider scoring below 0.5 on delisted coverage or below 0.25 on point-in-time fundamental availability is marked unsuitable regardless of its weighted total. Weights and thresholds live in versioned data (src/trp/bakeoff/weights.json, v2026-08-16.1) fixed before any real provider results exist.
Context: QUANT_PRINCIPLES §1 and §2 are non-negotiable; a weighted average can hide a fatal deficiency behind good scores elsewhere.
Alternatives: Weight inflation only (a bad provider can still win); manual judgement (unauditable).
Reason: A provider that cannot serve delisted securities cannot support survivorship-bias-free research at any price. The PIT threshold is set lower (0.25) because QNT-028's research already established that no provider in budget offers true PIT fundamentals — the criterion must be scored honestly without disqualifying every candidate.
Consequences: The report must show veto flags prominently. Revising weights/thresholds later requires a new weights-file version with justification; previously published scores remain attributable to their version.

---

DEC-013
Date: 2026-08-16
Decision: The QNT-028 Phase 1 provider purchase is executed. Owner subscribed to EODHD (paid monthly; 100,000 requests/day and extraLimit 500 observed via /api/user on 2026-08-16) and created a free Tiingo Starter account. Keys live in .env as TRP_EODHD_API_KEY / TRP_TIINGO_API_KEY (SecretStr; never logged — httpx request-URL logging is suppressed since it would print query-parameter tokens).
Context: DATA_PROVIDER_EVALUATION.md recommended EODHD ALL-IN-ONE month-to-month first, Tiingo free as US cross-check. Owner populated both keys on 2026-08-16.
Alternatives: Delay purchase; start with FMP.
Reason: EODHD is the only in-budget candidate covering UK prices, corporate actions, delisted securities and fundamentals in one subscription; the live bake-off run the same day confirmed LSE delisted coverage (all four validation delistings present with matching ISINs).
Consequences: The raw-payload archive is licensed, not owned — cancellation obliges deletion within one month, so the durable bake-off evidence is derived results, not raw payloads. Tier confirmed by the owner 2026-08-16: **ALL-IN-ONE Monthly Subscription, EUR 99.99/month** (month-to-month, as the QNT-028 recommendation advised — no annual commitment until the bake-off verdict is acted on). Live findings: EODHD UK fundamentals carry no usable publication timestamps (filing_date is a period-end default for ~99% of UK/EU rows), so DEC-007 imputation is confirmed load-bearing for UK point-in-time research; the pre-registered PIT veto (DEC-012) correctly marks both providers unsuitable *as PIT-fundamentals sources* while EODHD remains strong for prices/corporate actions/delisted coverage.

---

DEC-014
Date: 2026-08-18
Decision: FTSE 100 research coverage starts 2010-01-01. Membership remains queryable back to the curated anchor (2005-12-19) as event truth, but factor research and backtests must not extend before the coverage start; the universe registry exposes `research_coverage_start` and the QNT-041 gate enforces data completeness only within coverage.
Context: The QNT-091 backfill quantified EODHD's pre-2010 delisted gap — 48 of 240 historical FTSE 100 members (HBOS, Cadbury Schweppes, Xstrata, ICI, …) have no price data, nearly all pre-2010 departures. A backtest over that period would silently exclude ~20% of the then-universe: survivorship bias by data gap.
Alternatives: Patch the gap from another source (cost/effort unknown, deferred not rejected); keep the full span and per-date completeness checks (complex, still biased where incomplete).
Reason: 15+ years (2010–present) with verified full constituent data coverage is ample for medium-term factor research, and an honestly bounded span beats a longer contaminated one (QUANT_PRINCIPLES §2, §5).
Consequences: Backtests report their universe coverage start; results cannot claim pre-2010 UK evidence. Revisit if a source for pre-2010 delisted LSE data is ever acquired — the curated membership already extends to 2005, so only the price/fundamental gap would need filling.

---

DEC-015
Date: 2026-08-18
Decision: Factor definitions are JSON files under config/factors/, one file per immutable (name, version); in-place edits are detected by a declared content hash over the semantic body (description excluded); transforms are named Python implementations registered in trp.factors.compute — configuration parameterises them and can never express logic.
Context: QNT-042 requires versioned, reproducible factor definitions; the risk named in the ticket is an over-general configuration language.
Alternatives: YAML (adds a dependency and implicit typing quirks); Python modules as definitions (unhashable semantics, import-order coupling); a DSL (the trap itself).
Reason: JSON is already the repo's curated-data format, hashes canonically, and the closed transform registry keeps all logic in typed, tested Python.
Consequences: New transform kinds require code (deliberate friction); definition authors must recompute the hash on any semantic change, which is exactly the audit trail wanted. Stored values are tagged name@version + as_of + input dataset versions.
