"""An ad-hoc SQL console over every canonical and derived dataset (QNT-094).

Registers DuckDB views over the Parquet stores so the data can be interrogated directly,
without going through any platform code path::

    uv run python -m trp.explore                          # interactive SQL prompt
    uv run python -m trp.explore "SELECT ... FROM prices" # one-shot query

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

This is a read surface: the connection is opened read-only against the files, and nothing
here mutates a store.
"""

import sys

import duckdb

from trp.config import load_settings


def open_console() -> duckdb.DuckDBPyConnection:
    settings = load_settings()
    canonical = settings.canonical_dir
    derived = settings.derived_dir
    con = duckdb.connect()

    def view(name: str, sql: str) -> None:
        con.sql(f"CREATE OR REPLACE VIEW {name} AS {sql}")

    prices_glob = f"{canonical}/prices/*/part-*.parquet"
    view("prices", f"SELECT * FROM read_parquet('{prices_glob}') WHERE source = 'eodhd-gbx'")
    view(
        "prices_original",
        f"SELECT * FROM read_parquet('{prices_glob}') WHERE source <> 'eodhd-gbx'",
    )
    actions = canonical / "corporate_actions"
    view(
        "dividends",
        f"SELECT * FROM read_parquet('{actions}/eodhd_ftse100_dividends_gbx.parquet')",
    )
    view("splits", f"SELECT * FROM read_parquet('{actions}/eodhd_ftse100_splits_gbx.parquet')")
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


def main() -> None:
    con = open_console()
    if len(sys.argv) > 1:
        con.sql(" ".join(sys.argv[1:])).show(max_rows=100)
    else:
        repl(con)


if __name__ == "__main__":
    main()
