# Ticket index

Source of truth for the backlog. Statuses: BACKLOG · READY · IN_PROGRESS · BLOCKED · DONE.
Priorities: P1 = Milestone 1, P2 = Milestone 2, P3 = later. Update this file whenever a
ticket's status changes. **M1 critical path:** QNT-006 → 007 → 008 → 009 → 011 → 026 → 013 →
014 → 015 → 020 → 022 → 024 → 025 → 027 → 028 → 029 → adapters → 034/035 → 036 → 037 → 038 →
041.

## EPIC 1 — Project Foundation

| ID | Title | Priority | Status |
|---|---|---|---|
| [QNT-001](QNT-001-repository-scaffold.md) | Repository scaffold and package skeleton | P1 | DONE |
| [QNT-002](QNT-002-tooling-and-ci.md) | Lint, typecheck, test toolchain and CI | P1 | DONE |
| [QNT-003](QNT-003-config-and-logging.md) | Configuration and logging | P1 | DONE |
| [QNT-004](QNT-004-documentation-suite.md) | Documentation suite | P1 | DONE |
| [QNT-005](QNT-005-ticket-system-and-backlog.md) | Ticket system and initial backlog | P1 | DONE |

## EPIC 2 — Security Master

| ID | Title | Priority | Status |
|---|---|---|---|
| [QNT-006](QNT-006-security-master-domain-model.md) | Security master domain model | P1 | DONE |
| [QNT-007](QNT-007-identifier-mapping.md) | Identifier mapping with effective date ranges | P1 | DONE |
| [QNT-008](QNT-008-security-master-storage.md) | Security master storage (Parquet/DuckDB) | P1 | DONE |
| [QNT-009](QNT-009-identifier-resolution.md) | Identifier resolution service | P1 | DONE |
| [QNT-010](QNT-010-corporate-change-handling.md) | Ticker, listing and status change handling | P1 | DONE |
| [QNT-011](QNT-011-pit-security-lookup.md) | Point-in-time security lookup API | P1 | DONE |
| [QNT-012](QNT-012-security-master-lifecycle-tests.md) | Security master lifecycle test suite | P1 | DONE |

## EPIC 3 — Market Data

| ID | Title | Priority | Status |
|---|---|---|---|
| [QNT-013](QNT-013-ohlcv-schema.md) | Canonical daily OHLCV schema | P1 | DONE |
| [QNT-014](QNT-014-corporate-action-schema.md) | Corporate action canonical schema | P1 | DONE |
| [QNT-015](QNT-015-adjustment-engine.md) | Adjustment factor engine | P1 | DONE |
| [QNT-016](QNT-016-trading-calendars.md) | Trading calendars | P1 | DONE |
| [QNT-017](QNT-017-exchange-currency-metadata.md) | Exchange and currency metadata | P1 | DONE |
| [QNT-018](QNT-018-price-storage-partitioning.md) | Price storage layout and partitioning | P1 | DONE |
| [QNT-019](QNT-019-market-data-validation.md) | Market data validation checks | P1 | DONE |
| [QNT-091](QNT-091-eodhd-canonical-ingestion.md) | EODHD canonical ingestion pipeline | P1 | DONE |
| [QNT-092](QNT-092-first-momentum-tearsheet.md) | First real backtest: momentum tearsheet | P1 | DONE |
| [QNT-093](QNT-093-price-unit-normalisation.md) | GBX/GBP unit normalisation (prices, dividends) | P1 | DONE |
| [QNT-094](QNT-094-data-exploration-surface.md) | Ad-hoc data exploration surface | P2 | DONE |
| [QNT-095](QNT-095-notebook-and-ide-access.md) | Notebook and IDE (JDBC) data access | P2 | DONE |
| [QNT-096](QNT-096-uk-risk-free-series.md) | UK risk-free series (3M gilt) | P2 | DONE |
| [QNT-097](QNT-097-eodhd-fundamentals-canonicalisation.md) | EODHD fundamentals backfill + canonicalisation | P1 | DONE |

## EPIC 4 — Fundamental Data

| ID | Title | Priority | Status |
|---|---|---|---|
| [QNT-020](QNT-020-pit-fundamental-schema.md) | Point-in-time fundamental schema | P1 | DONE |
| [QNT-021](QNT-021-statement-normalisation.md) | Financial statement normalisation model | P1 | DONE |
| [QNT-022](QNT-022-revision-handling.md) | Revision and restatement handling | P1 | DONE |
| [QNT-023](QNT-023-fundamental-currency.md) | Fundamental currency handling | P1 | DONE |
| [QNT-024](QNT-024-fundamental-storage.md) | Fundamental storage layout | P1 | DONE |
| [QNT-025](QNT-025-asof-fundamental-queries.md) | As-of fundamental query API and time-travel tests | P1 | DONE |

## EPIC 5 — Data Provider Bake-Off

| ID | Title | Priority | Status |
|---|---|---|---|
| [QNT-026](QNT-026-provider-interface.md) | Common provider interface and raw ingestion layer | P1 | DONE |
| [QNT-027](QNT-027-validation-universe.md) | Validation universe specification | P1 | DONE |
| [QNT-028](QNT-028-provider-research-report.md) | Provider research and shortlist report (owner gate) | P1 | DONE |
| [QNT-029](QNT-029-bakeoff-harness.md) | Bake-off harness core | P1 | DONE |
| [QNT-030](QNT-030-scoring-rubric.md) | Scoring rubric and criteria weights | P1 | DONE |
| [QNT-031](QNT-031-eodhd-adapter.md) | EODHD provider adapter | P1 | DONE |
| [QNT-032](QNT-032-fmp-adapter.md) | Financial Modeling Prep provider adapter | P1 | BLOCKED |
| [QNT-033](QNT-033-tiingo-adapter.md) | Tiingo provider adapter | P1 | DONE |
| [QNT-034](QNT-034-corporate-action-checks.md) | Corporate-action and price accuracy checks | P1 | DONE |
| [QNT-035](QNT-035-pit-fundamental-checks.md) | PIT fundamental and revision checks | P1 | DONE |
| [QNT-036](QNT-036-provider-comparison-report.md) | Automated provider comparison report | P1 | DONE |

## EPIC 6 — Historical Universe Engine

| ID | Title | Priority | Status |
|---|---|---|---|
| [QNT-037](QNT-037-universe-membership-schema.md) | Universe membership schema and storage | P1 | DONE |
| [QNT-038](QNT-038-universe-query-api.md) | Universe membership query API | P1 | DONE |
| [QNT-039](QNT-039-ftse-membership-sourcing.md) | FTSE index membership sourcing | P1 | DONE |
| [QNT-040](QNT-040-broad-uk-universe.md) | Broad UK-listed universe construction | P1 | READY |
| [QNT-041](QNT-041-universe-survivorship-tests.md) | Universe survivorship test suite | P1 | DONE |

## EPIC 7 — Factor Engine

| ID | Title | Priority | Status |
|---|---|---|---|
| [QNT-042](QNT-042-factor-framework.md) | Versioned factor definition framework | P2 | DONE |
| [QNT-043](QNT-043-returns-library.md) | Returns library | P2 | DONE |
| [QNT-044](QNT-044-momentum-factors.md) | Momentum factor set | P2 | DONE |
| [QNT-045](QNT-045-quality-factors.md) | Quality factor set | P2 | BACKLOG |
| [QNT-046](QNT-046-value-factors.md) | Value factor set | P2 | BACKLOG |
| [QNT-047](QNT-047-cross-sectional-transforms.md) | Cross-sectional transforms | P2 | BACKLOG |
| [QNT-048](QNT-048-composite-scoring.md) | Composite factor scoring | P2 | BACKLOG |
| [QNT-049](QNT-049-factor-pit-tests.md) | Factor point-in-time test suite | P2 | BACKLOG |

## EPIC 8 — Backtesting Engine

| ID | Title | Priority | Status |
|---|---|---|---|
| [QNT-050](QNT-050-backtest-core.md) | Backtest engine core and PIT data access | P2 | DONE |
| [QNT-051](QNT-051-portfolio-accounting.md) | Portfolio accounting | P2 | DONE |
| [QNT-052](QNT-052-rebalancing-weighting.md) | Rebalancing and weighting schemes | P2 | DONE |
| [QNT-053](QNT-053-costs-slippage.md) | Transaction costs and slippage | P2 | DONE |
| [QNT-054](QNT-054-performance-metrics.md) | Performance metrics suite | P2 | DONE |
| [QNT-055](QNT-055-benchmark-relative.md) | Benchmark and relative performance | P2 | DONE |
| [QNT-056](QNT-056-rolling-statistics.md) | Rolling statistics | P2 | DONE |
| [QNT-057](QNT-057-backtest-leakage-tests.md) | Backtest correctness and leakage regression suite | P2 | DONE |

## EPIC 9 — Risk Engine

| ID | Title | Priority | Status |
|---|---|---|---|
| [QNT-058](QNT-058-exposure-calculations.md) | Exposure calculations | P2 | BACKLOG |
| [QNT-059](QNT-059-vol-beta-correlation.md) | Volatility, beta, correlation, covariance | P2 | BACKLOG |
| [QNT-060](QNT-060-drawdown-concentration-turnover.md) | Drawdown, concentration and turnover metrics | P2 | BACKLOG |
| [QNT-061](QNT-061-var-es-scenarios.md) | Historical VaR, expected shortfall, scenario shocks | P2 | BACKLOG |
| [QNT-062](QNT-062-unified-risk-interface.md) | Unified risk interface for simulated and live portfolios | P2 | BACKLOG |

## EPIC 10 — Research Experiment Registry

| ID | Title | Priority | Status |
|---|---|---|---|
| [QNT-063](QNT-063-experiment-schema.md) | Experiment registry schema | P2 | BACKLOG |
| [QNT-064](QNT-064-run-capture-manifest.md) | Run capture and reproducibility manifest | P2 | BACKLOG |
| [QNT-065](QNT-065-results-persistence.md) | Results persistence and retrieval | P2 | BACKLOG |
| [QNT-066](QNT-066-hypothesis-workflow.md) | Hypothesis–experiment–evidence–conclusion workflow | P2 | BACKLOG |

## EPIC 11 — Portfolio Construction

| ID | Title | Priority | Status |
|---|---|---|---|
| [QNT-067](QNT-067-weighting-schemes.md) | Weighting schemes library | P3 | BACKLOG |
| [QNT-068](QNT-068-volatility-targeting.md) | Volatility targeting and risk parity concepts | P3 | BACKLOG |
| [QNT-069](QNT-069-constraint-framework.md) | Constraint framework | P3 | BACKLOG |
| [QNT-070](QNT-070-optimisation-stability.md) | Optimisation with stability controls | P3 | BACKLOG |
| [QNT-071](QNT-071-portfolio-validation-tests.md) | Portfolio construction validation suite | P3 | BACKLOG |

## EPIC 12 — Research API

| ID | Title | Priority | Status |
|---|---|---|---|
| [QNT-072](QNT-072-fastapi-skeleton.md) | FastAPI application skeleton | P3 | BACKLOG |
| [QNT-073](QNT-073-data-endpoints.md) | Securities, prices and fundamentals endpoints | P3 | BACKLOG |
| [QNT-074](QNT-074-research-endpoints.md) | Factors, universes, backtests and experiments endpoints | P3 | BACKLOG |
| [QNT-075](QNT-075-risk-signal-endpoints.md) | Risk and signal endpoints | P3 | BACKLOG |

## EPIC 13 — Research Terminal

| ID | Title | Priority | Status |
|---|---|---|---|
| [QNT-076](QNT-076-terminal-skeleton.md) | Research terminal application skeleton | P3 | BACKLOG |
| [QNT-077](QNT-077-screener-factor-views.md) | Screener and factor views | P3 | BACKLOG |
| [QNT-078](QNT-078-company-detail-view.md) | Company detail view | P3 | BACKLOG |
| [QNT-079](QNT-079-portfolio-backtest-views.md) | Portfolio, risk and backtest views | P3 | BACKLOG |

## EPIC 14 — LLM Research Interface

| ID | Title | Priority | Status |
|---|---|---|---|
| [QNT-080](QNT-080-llm-tool-surface.md) | Deterministic tool surface for LLM | P3 | BACKLOG |
| [QNT-081](QNT-081-signal-explanation.md) | Signal explanation service | P3 | BACKLOG |
| [QNT-082](QNT-082-llm-guardrails.md) | LLM guardrails and evaluation | P3 | BACKLOG |

## EPIC 15 — Paper Trading

| ID | Title | Priority | Status |
|---|---|---|---|
| [QNT-083](QNT-083-broker-abstraction.md) | Broker abstraction layer | P3 | BACKLOG |
| [QNT-084](QNT-084-ibkr-paper-adapter.md) | Interactive Brokers paper adapter | P3 | BACKLOG |
| [QNT-085](QNT-085-reconciliation.md) | Position and cash reconciliation | P3 | BACKLOG |
| [QNT-086](QNT-086-order-fill-capture.md) | Order and fill capture | P3 | BACKLOG |

## EPIC 16 — Live Trading

| ID | Title | Priority | Status |
|---|---|---|---|
| [QNT-087](QNT-087-env-separation-kill-switch.md) | Live/paper environment separation and kill switch | P3 | BACKLOG |
| [QNT-088](QNT-088-order-safeguards.md) | Order safeguards | P3 | BACKLOG |
| [QNT-089](QNT-089-stale-duplicate-detection.md) | Stale-data and duplicate-order detection | P3 | BACKLOG |
| [QNT-090](QNT-090-audit-trail.md) | Audit trail | P3 | BACKLOG |
