"""An ad-hoc SQL console over every canonical and derived dataset (QNT-094).

Registers DuckDB views over the Parquet stores so the data can be interrogated directly,
without going through any platform code path::

    uv run python -m trp.explore                          # interactive SQL prompt
    uv run python -m trp.explore "SELECT ... FROM prices" # one-shot query
    uv run python -m trp.explore --build-db               # (re)build data/trp.duckdb for
                                                          # DataGrip/DBeaver/JDBC clients

Views (see ``docs/QUERYING.md`` for a cookbook):

- ``prices``             repaired GBX bars only (DEC-020, source = eodhd-gbx) — the ones
                         research uses
- ``prices_original``    the untouched provider rows (kept for audit; units are dirty)
- ``dividends``/``splits``            unit-repaired corporate actions
- ``dividends_original``/``splits_original``  as ingested
- ``membership``         bitemporal universe membership spells
- ``securities``/``identifiers``/``listings``/``entities``   the security master
- ``backtest_daily``/``backtest_events``/``backtest_rebalances``  every persisted run,
                         with a ``run`` column from the directory name
- ``fundamentals``       point-in-time statement store (available_at is load-bearing)
- ``fx_gbpusd``/``fx_gbpeur``/``risk_free``/``benchmark_bars``  the auxiliary series
- ``factor_values``      materialised factor cross-sections, long form
- ``factor_panel``       the same data wide: one row per (security, end), a column per
                         factor, NULL where not computable — the analysis shape

This is a read surface: the connection is opened read-only against the files, and nothing
here mutates a store.
"""

import sys
from pathlib import Path

import duckdb

from trp.config import load_settings


def open_console(database: str = ":memory:") -> duckdb.DuckDBPyConnection:
    settings = load_settings()
    # Absolute paths: the view definitions are persisted into data/trp.duckdb, where an
    # IDE opens them from an arbitrary working directory.
    canonical = settings.canonical_dir.resolve()
    derived = settings.derived_dir.resolve()
    con = duckdb.connect(database)

    def view(name: str, sql: str) -> None:
        con.sql(f"CREATE OR REPLACE VIEW {name} AS {sql}")

    from trp.canonical.unit_repair import ORIGINAL_SOURCE, REPAIRED_SOURCE

    prices_glob = f"{canonical}/prices/*/part-*.parquet"
    view(
        "prices",
        f"SELECT * FROM read_parquet('{prices_glob}') WHERE source = '{REPAIRED_SOURCE}'",
    )
    view(
        "prices_original",
        f"SELECT * FROM read_parquet('{prices_glob}') WHERE source = '{ORIGINAL_SOURCE}'",
    )
    actions = canonical / "corporate_actions"
    from trp.canonical.unit_repair import DIVIDENDS_FILE, SPLITS_FILE

    view("dividends", f"SELECT * FROM read_parquet('{actions}/{DIVIDENDS_FILE}')")
    view("splits", f"SELECT * FROM read_parquet('{actions}/{SPLITS_FILE}')")
    view(
        "dividends_original",
        f"SELECT * FROM read_parquet('{actions}/eodhd_ftse100_dividends.parquet')",
    )
    view(
        "splits_original",
        f"SELECT * FROM read_parquet('{actions}/eodhd_ftse100_splits.parquet')",
    )
    view(
        "membership",
        f"SELECT * FROM read_parquet('{canonical}/universes/*/membership.parquet')",
    )
    for table in ("securities", "identifiers", "listings", "entities"):
        view(table, f"SELECT * FROM read_parquet('{canonical}/securities/{table}.parquet')")
    view(
        "fundamentals",
        f"SELECT * FROM read_parquet('{canonical}/fundamentals/*/part-*.parquet')",
    )
    view("fx_gbpusd", f"SELECT * FROM read_parquet('{canonical}/fx/gbpusd.parquet')")
    view("fx_gbpeur", f"SELECT * FROM read_parquet('{canonical}/fx/gbpeur.parquet')")
    view(
        "risk_free",
        f"SELECT * FROM read_parquet('{canonical}/riskfree/uk3m-gbond/series.parquet')",
    )
    view(
        "benchmark_bars",
        "SELECT parse_filename(parse_dirpath(filename)) AS benchmark, * EXCLUDE (filename) "
        f"FROM read_parquet('{canonical}/benchmarks/*/bars.parquet', filename = true)",
    )
    # Factor values appear once materialised to the derived store (the QNT-048
    # pipeline writes them); DuckDB refuses a view over an empty glob, so skip until then.
    if any((derived / "factors").rglob("*.parquet")):
        view(
            "factor_values",
            f"SELECT * FROM read_parquet('{derived}/factors/*/*/*.parquet', "
            "union_by_name = true, hive_partitioning = true)",
        )
        # The analysis-friendly wide shape: one row per (security, end), one column per
        # factor, NULL where that factor was not 'ok' (missingness stays visible). The
        # column set is fixed at build time from the materialised names — rerun
        # `make db` after materialising a new factor.
        names = [
            row[0]
            for row in con.sql("SELECT DISTINCT name FROM factor_values ORDER BY name").fetchall()
        ]
        columns = ",\n            ".join(
            f"max(CASE WHEN name = '{name}' AND status = 'ok' THEN value END) AS {name}"
            for name in names
        )
        view(
            "factor_panel",
            f'SELECT security_id, "end", {columns} FROM factor_values GROUP BY security_id, "end"',
        )
    for name, filename in (
        ("backtest_daily", "daily.parquet"),
        ("backtest_events", "events.parquet"),
        ("backtest_rebalances", "rebalances.parquet"),
    ):
        view(
            name,
            "SELECT parse_filename(parse_dirpath(filename)) AS run, * EXCLUDE (filename) "
            f"FROM read_parquet('{derived}/backtests/*/{filename}', filename = true)",
        )
    return con


_HELP = """Views: prices, prices_original, dividends, splits, dividends_original,
splits_original, membership, securities, identifiers, listings, entities,
backtest_daily, backtest_events, backtest_rebalances.
Commands: \\d <view> describes it; quit/exit leaves. Cookbook: docs/QUERYING.md"""


def repl(con: duckdb.DuckDBPyConnection) -> None:
    print(_HELP)
    while True:
        try:
            query = input("sql> ").strip()
        except (EOFError, KeyboardInterrupt):
            print()
            return
        if not query:
            continue
        if query.lower() in {"quit", "exit", r"\q"}:
            return
        if query.startswith("\\d "):
            query = f"DESCRIBE {query[3:]}"
        try:
            con.sql(query).show(max_rows=50)
        except duckdb.Error as error:
            print(error)


def build_database() -> Path:
    """(Re)create ``data/trp.duckdb`` for IDE/JDBC clients (DataGrip, DBeaver, ...).

    The file holds only view definitions over the Parquet stores — no data is copied.
    Built into a scratch file and atomically swapped into place, because ANY open DuckDB
    connection (read-only included) holds a file lock: an attached IDE session keeps
    reading its old inode and picks up the new views on its next reconnect/refresh."""
    import os

    settings = load_settings()
    target = settings.data_dir.resolve() / "trp.duckdb"
    scratch = target.with_suffix(".duckdb.building")
    scratch.unlink(missing_ok=True)
    open_console(str(scratch)).close()
    os.replace(scratch, target)
    return target


def main() -> None:
    if "--build-db" in sys.argv:
        print(f"database ready: {build_database()}")
        return
    con = open_console()
    if len(sys.argv) > 1:
        con.sql(" ".join(sys.argv[1:])).show(max_rows=100)
    else:
        repl(con)


if __name__ == "__main__":
    main()
