# Architecture

Single-machine, simple, inspectable. Python package `trp` (src layout, typed, mypy strict).
No microservices, no distributed computing, no orchestration framework until data volume or
latency demonstrably demands it.

## Layers

```
providers  ──►  ingestion (raw, immutable)  ──►  canonical  ──►  derived
   │                                                 │              │
   └─ EODHD / FMP / Tiingo adapters                  │              ├─ factors
      behind one MarketDataProvider interface        │              ├─ returns
                                                     │              └─ risk
                       consumers: universe engine, factor engine, backtester,
                       risk engine, experiment registry, API, terminal, execution
```

- **`trp.providers`** — `MarketDataProvider` abstract interface (securities, prices,
  corporate_actions, fundamentals, financial_periods, delisted_securities) plus one adapter per
  provider. Adapters translate transport/auth/pagination only; they do not normalise semantics.
- **`trp.ingestion`** — fetches via adapters and writes provider payloads **verbatim** to
  `data/raw/<provider>/…` with fetch timestamp, endpoint, and parameters. Raw data is immutable
  and append-only; it is the audit trail and the reprocessing source. Never discarded unless
  licensing forbids storage.
- **`trp.canonical`** — deterministic, re-runnable transforms from raw to the canonical model
  (see `DATA_MODEL.md`): security master, prices, corporate actions, fundamentals, universes.
  Stored as Parquet under `data/canonical/…`, queried via DuckDB and Polars.
- **Derived** — factors, returns, risk statistics computed from canonical data into
  `data/derived/…`, always tagged with the versions of their inputs and definitions.
- **`trp.bakeoff`** — provider evaluation harness: a deliberately awkward validation universe,
  empirical checks, scoring, and a generated comparison report (`DATA_PROVIDER_EVALUATION.md`).

Later packages (created when their epic starts): `universe`, `factors`, `backtest`, `risk`,
`experiments`, `portfolio`, `api` (FastAPI), and a separate web frontend.

## Storage

- **Parquet + DuckDB** for all analytical/historical data. Partition intelligently (e.g. prices
  by year), avoiding excessive tiny files.
- **PostgreSQL deferred** (DEC-004) until there is genuinely transactional state (experiment
  registry writes, paper-trading orders). Milestone 1 has none.
- `data/` is gitignored; code + raw payloads reproduce everything else.

## Conventions

- Timestamps: timezone-aware UTC. Market-local calendar concepts (trading day, period end) are
  dates.
- `Decimal` in canonical stores for prices/dividends/per-share values; floats in derived
  analytics where vectorised performance matters.
- Pydantic v2 frozen models for domain records at the boundaries; Polars dataframes for bulk
  set-based work; SQL (DuckDB) where set logic reads better.
- Every historical read API takes `as_of`.

## Execution boundary (future)

Signal generation and order execution stay separate components with an explicit interface.
Live and paper environments are physically separated configurations with independent
credentials, plus kill switch, order-size/weight limits, price sanity checks, stale-data and
duplicate-order detection, and an append-only audit trail (Epic 16).
