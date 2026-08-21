# Doing research and interrogating the data yourself

Start with the lab if you are running an experiment; drop to SQL when you have an ad-hoc
question about the data itself.

## 0. The lab (run and evaluate experiments — the front door)

```python
from trp import lab

exp = lab.design(
    "qvm-ftse250-oos",              # experiment name (also the run-record prefix)
    factor="qvm_equal",
    universe="FTSE250",
    hypothesis="QVM's IR advantage survives out of sample",   # or an existing "HYP-..." id
    rationale="in-sample result needs an untouched test set",
    tags=("out-of-sample",),
)
run_id = lab.run(exp)               # backtest + manifest + metrics + report.html, digest printed
lab.compare("qvm-*")                # aligned metrics frame across matching experiments
lab.report("qvm-*")                 # single-page HTML comparison of their latest runs
lab.conclude(exp, "supported", text="...", weaknesses=["..."])
```

That is the whole loop: idea → registered experiment → run → evaluation → recorded
conclusion, without leaving Python. `lab.run` writes **`report.html` inside the run
record** — equity vs benchmark, drawdown, rolling Sharpe, annual excess, costs, warnings —
fully self-contained (open it in any browser, `lab.open_in_browser(path)` if lazy).

The lab is a facade over the experiment registry, never a bypass: hypotheses precede
experiments, manifests capture automatically, a dirty working tree poisons confirmatory
evidence, and the variant counter still triggers the multiple-testing warning. Defaults
are the platform's honest ones (DEC-014 start, pessimistic costs, ISF total-return
benchmark); every default is overridable per call. `lab.experiments()`, `lab.results(name)`
and the `experiments`/`runs` SQL tables below give you the audit trail.

Everything below is read-only interrogation of the underlying stores.

## The one trap to know first

The price store is append-only, so **two copies of every bar coexist**:

- `source = 'eodhd-gbx2'` — the DEC-020 unit-repaired rows (v2 adds the Melrose
  segment adjudication). **Use these.**
- `source = 'eodhd'` — the provider's original rows, kept for audit. Some series are in
  pounds, some flip units mid-history (see `data/canonical/corporate_actions/unit_repair_report_gbx2.json`).

A naive glob over `data/canonical/prices/**` returns both and doubles every row. The SQL
console below already filters for you; if you query the files directly, filter on `source`.

## 1. SQL console (ad-hoc questions)

```sh
uv run python -m trp.explore                      # interactive prompt
uv run python -m trp.explore "SELECT ..."         # one-shot
```

Views: `prices` (repaired GBX), `prices_original`, `dividends`, `splits` (+`_original`
variants), `membership`, `securities`, `identifiers`, `listings`, `entities`,
`backtest_daily`, `backtest_events`, `backtest_rebalances`. `\d <view>` describes one.

Worked examples:

```sql
-- A price history by company name
SELECT p.trade_date, p.close, p.volume
FROM prices p JOIN securities s USING (security_id)
WHERE s.name LIKE 'AstraZeneca%' AND p.trade_date >= DATE '2024-01-01'
ORDER BY p.trade_date;

-- Who was in the FTSE 100 on a date (current knowledge)?
SELECT s.name, m.valid_from, m.valid_to
FROM membership m JOIN securities s USING (security_id)
WHERE m.universe = 'FTSE100' AND m.superseded_at IS NULL
  AND DATE '2007-08-15' >= m.valid_from
  AND (m.valid_to IS NULL OR DATE '2007-08-15' < m.valid_to)
ORDER BY s.name;   -- Northern Rock and HBOS are in there: no survivorship bias

-- Dividend history with units made explicit
SELECT ex_date, amount, currency, special
FROM dividends d JOIN securities s USING (security_id)
WHERE s.name LIKE 'Admiral%' ORDER BY ex_date DESC;

-- What did the backtest actually do? Every fill, dividend and exit is an event.
SELECT "on", kind, quantity_delta, cash_delta, price, note
FROM backtest_events
WHERE run = 'momentum-12-1-ftse100-monthly-to-2026-08-17'
ORDER BY "on" LIMIT 50;

-- Costs and turnover per rebalance
SELECT date, trades, round(turnover, 3) AS turnover, round(costs / 100, 0) AS costs_gbp
FROM backtest_rebalances ORDER BY date;
```

The console is plain DuckDB — joins, window functions, `COPY (...) TO 'out.csv'` all work.

## 2. Polars / DuckDB in your own scripts

```python
import polars as pl

bars = pl.read_parquet("data/canonical/prices/*/part-*.parquet").filter(
    pl.col("source") == "eodhd-gbx"
)
```

Or `from trp.explore import open_console` gives you the same connection with all views
registered, e.g. `open_console().sql("...").pl()` for a Polars frame.

## 3. The point-in-time APIs (what research code must use)

Direct file reads answer "what does the store contain?". They do NOT answer "what was
knowable on date X?" — that is what the `as_of` APIs are for, and any research question
must go through them:

```python
from datetime import UTC, date, datetime
from trp.config import load_settings
from trp.universe.query import UniverseQuery

query = UniverseQuery(load_settings().canonical_dir / "universes")
members = query.members(
    "FTSE100", date(2015, 6, 30), as_of=datetime(2015, 7, 1, tzinfo=UTC)
)
```

`trp.canonical.price_store.read_prices(..., as_of=...)` bounds by `ingested_at` the same
way, and fundamentals go through `trp.canonical.fundamentals.queries.fundamentals(...)`
only.

## Where everything lives

| Path | Contents |
|---|---|
| `data/raw/eodhd/` | Immutable provider payloads, exactly as fetched (never edited) |
| `data/canonical/prices/` | Daily bars, Hive-partitioned by trade year; two sources per the trap above |
| `data/canonical/corporate_actions/` | Dividends/splits (`*_gbx` = repaired) + `unit_repair_report.json` (every repair decision with evidence) |
| `data/canonical/universes/` | Bitemporal membership spells (valid_from/to + recorded_at/superseded_at) |
| `data/canonical/securities/` | Security master: securities, identifiers, listings, entities |
| `data/derived/backtests/<run>/` | Immutable run records: config.json, meta.json (config hash + git commit), daily/events/rebalances parquet, metrics.json |
| `docs/tearsheets/` | Human-readable run summaries |

## Notebooks

```sh
make lab        # JupyterLab, opening in notebooks/
```

`notebooks/explore.ipynb` is a worked starter: SQL-to-Polars, the momentum run's equity
curve, the survivorship check, and a point-in-time query. JupyterLab and matplotlib are
dev dependencies (`uv sync` installs them).

## DataGrip / DBeaver / any JDBC client

```sh
make db         # (re)builds data/trp.duckdb
```

That file contains only VIEW definitions over the Parquet stores — no data is copied, so
it is always current and cheap to rebuild after new ingestions. Connect from the IDE:

1. New data source -> **DuckDB** (DataGrip and DBeaver bundle the driver; if yours is
   older than the local duckdb 1.5.x it may refuse the file — update the driver from the
   IDE's driver settings).
2. Path: `<repo>/data/trp.duckdb`.
3. Set the connection **read-only** (driver property `duckdb.read_only = true`). DuckDB
   files take an exclusive lock for writers, so a read-only IDE session never collides
   with `make db` or anything else.

All the same views are there: `prices`, `membership`, `backtest_events`, and so on.

For an interactive native shell instead: `brew install duckdb`, then either open
`data/trp.duckdb` or use the same `read_parquet` globs directly.
