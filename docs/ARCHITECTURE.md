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

- **`trp.providers`** — `MarketDataProvider` abstract interface (implemented, QNT-026):
  `securities`, `prices`, `corporate_actions`, `fundamentals`, `financial_periods`,
  `delisted_securities`, each yielding `RawPayload` pages (verbatim bytes + logical request
  params, credentials excluded). Adapters declare `name`/`version`/`capabilities`; an
  unsupported dataset raises `ProviderCapabilityError` — distinct from an empty result — and
  throttling/outage raise `ProviderRateLimitError`/`ProviderUnavailableError` so the bake-off
  can tell "no such data" from "we were throttled". Adapters translate transport, auth,
  pagination and rate limits only; they never normalise semantics.
- **`trp.ingestion`** — `RawStore` (implemented, QNT-026) writes payloads **verbatim** to
  `data/raw/<provider>/<dataset>/<params_hash>/<fetched_at>-<n>.{json,csv,bin}` with a
  `.meta.json` sidecar (provider, version, endpoint, sanitised params, param hash, UTC fetch
  timestamp, content SHA-256). Append-only and immutable: re-fetches append, nothing is ever
  overwritten or deleted, and there is no delete method. A per-write `retain=False` flag
  (licensing) stores the sidecar with content hash only. Credential-shaped parameter keys are
  stripped before hashing or writing.
- **`trp.canonical`** — deterministic, re-runnable transforms from raw to the canonical model
  (see `DATA_MODEL.md`): security master, prices, corporate actions, fundamentals, universes.
  Stored as Parquet under `data/canonical/…`, queried via DuckDB and Polars.
- **Derived** — factors, returns, risk statistics computed from canonical data into
  `data/derived/…`, always tagged with the versions of their inputs and definitions.
- **`trp.bakeoff`** — provider evaluation harness: a deliberately awkward validation universe,
  empirical checks, scoring, and a generated comparison report (`DATA_PROVIDER_EVALUATION.md`).

- **`trp.universe`** — time-indexed universe membership (QNT-037/038): bitemporal spells
  in Parquet per universe; `UniverseQuery.members(universe, date, *, as_of)` is the ONLY
  supported way to obtain a universe — `date` is the simulated calendar date, `as_of` is
  knowledge time, and out-of-coverage dates raise rather than returning an empty set.

Later packages (created when their epic starts): `factors`, `backtest`, `risk`,
`experiments`, `portfolio`, `api` (FastAPI), and a separate web frontend.

## Storage

- **Parquet + DuckDB** for all analytical/historical data. Partition intelligently, avoiding
  excessive tiny files: fundamentals are partitioned by period-end year with append-only
  part-files (DEC-011); prices will partition by year (QNT-018). The fundamentals dataset is
  read ONLY through `trp.canonical.fundamentals.queries.fundamentals(...)` — the single as-of
  choke point; direct Parquet reads in research code are forbidden.
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
