"""Run a factor backtest over the canonical datasets and write the full record (QNT-092).

This is the assembly point: canonical prices/dividends/splits from disk -> ``MarketData``
(with dataset versions recorded), the survivorship-free ``UniverseQuery``, the factor
registry, the engine, metrics, and a markdown tearsheet under ``docs/tearsheets/``.

Bars are loaded from a lookback buffer before ``config.start`` (momentum needs ~13 months
of history at the first rebalance) through ``config.end``. Everything after loading goes
through the clock-bound context — the loader's date bounds are a superset, never a
point-in-time filter.

Usage::

    uv run python -m trp.backtest.runner            # the default FTSE 100 momentum run
"""

import hashlib
import logging
from datetime import date, timedelta
from decimal import Decimal
from pathlib import Path

import polars as pl

from trp.backtest.config import BacktestConfig
from trp.backtest.engine import BacktestEngine, MarketData, RunResult, write_run
from trp.backtest.metrics import MetricsRecord, compute_metrics, write_metrics
from trp.backtest.rebalance import factor_strategy
from trp.canonical.price_store import read_bars
from trp.canonical.unit_repair import REPAIRED_SOURCE
from trp.config import load_settings
from trp.domain.corporate_actions import CorporateAction, Dividend, Split
from trp.factors.registry import FactorRegistry
from trp.universe.query import UniverseQuery

logger = logging.getLogger(__name__)

LOOKBACK_BUFFER_DAYS = 450
"""Calendar days of bars loaded before config.start — covers 12-1 momentum + volatility."""


def _file_digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()[:12]


def load_actions(actions_dir: Path) -> tuple[list[CorporateAction], dict[str, str]]:
    actions: list[CorporateAction] = []
    versions: dict[str, str] = {}
    # QNT-093 unit-repaired datasets: prices under source=eodhd-gbx, *_gbx action files.
    dividends_path = actions_dir / "eodhd_ftse100_dividends_gbx.parquet"
    splits_path = actions_dir / "eodhd_ftse100_splits_gbx.parquet"
    for row in pl.read_parquet(dividends_path).iter_rows(named=True):
        actions.append(Dividend.model_validate(row))
    for row in pl.read_parquet(splits_path).iter_rows(named=True):
        actions.append(Split.model_validate(row))
    versions["actions:dividends"] = _file_digest(dividends_path)
    versions["actions:splits"] = _file_digest(splits_path)
    return actions, versions


def load_market(config: BacktestConfig) -> MarketData:
    settings = load_settings()
    load_start = config.start - timedelta(days=LOOKBACK_BUFFER_DAYS)
    logger.info("loading canonical bars %s..%s", load_start, config.end)
    bars = read_bars(
        settings.canonical_dir / "prices",
        start=load_start,
        end=config.end,
        sources=[REPAIRED_SOURCE],
    )
    logger.info("loaded %d bars", len(bars))
    actions, versions = load_actions(settings.canonical_dir / "corporate_actions")
    logger.info("loaded %d corporate actions", len(actions))
    versions["prices"] = f"{len(bars)} bars {load_start}..{config.end}"
    return MarketData(bars, actions, versions)


def default_ftse100_momentum_config(end: date) -> BacktestConfig:
    """The first research configuration: DEC-014 coverage start, monthly top-20 equal
    weight 12-1 momentum, shipped pessimistic costs, £1m starting capital (GBX)."""
    return BacktestConfig(
        name=f"momentum-12-1-ftse100-monthly-to-{end.isoformat()}",
        start=date(2010, 1, 1),
        end=end,
        universe="FTSE100",
        factor="momentum_12_1",
        factor_version=1,
        top_n=20,
        initial_cash=Decimal("100000000"),  # 100m GBX = £1m
        benchmark=None,
        data_versions={},
    )


def run(config: BacktestConfig) -> tuple[RunResult, MetricsRecord, Path]:
    settings = load_settings()
    market = load_market(config)
    universe_query = UniverseQuery(settings.canonical_dir / "universes")
    strategy = factor_strategy(FactorRegistry.load().get(config.factor), config)
    engine = BacktestEngine(config, market, universe_query)
    logger.info("running %s (%s)", config.name, config.config_hash())
    result = engine.run(strategy)
    directory = write_run(result, settings.derived_dir / "backtests")
    record = compute_metrics(
        result.daily.select("date", "value"),
        result.events,
        periods_per_year=252,
        risk_free_rate=0.0,
        risk_free_source="assumed zero (no risk-free series ingested yet; overstates Sharpe)",
    )
    write_metrics(record, directory)
    logger.info("run record written to %s", directory)
    return result, record, directory


def render_tearsheet(result: RunResult, record: MetricsRecord, directory: Path) -> str:
    config = result.config

    def pct(x: float | None) -> str:
        return f"{x:+.2%}" if x is not None else "n/a"

    def num(x: float | None) -> str:
        return f"{x:.2f}" if x is not None else "n/a"

    rebalances = result.rebalances
    total_costs = float(rebalances["costs"].sum() or 0.0) if rebalances.height else 0.0
    mean_turnover_value = rebalances["turnover"].mean() if rebalances.height else 0.0
    mean_turnover = (
        float(mean_turnover_value) if isinstance(mean_turnover_value, int | float) else 0.0
    )
    final_value = float(result.daily["value"][-1])
    initial = float(config.initial_cash)
    annual_lines = "\n".join(
        f"| {year} | {pct(value)} |" for year, value in sorted(record.annual_returns.items())
    )
    flags = "\n".join(f"- {flag}" for flag in record.flags) or "- none"
    warning_count = len(result.warnings)
    forced_exits = sum(1 for w in result.warnings if "forced exit" in w)

    return f"""# Tearsheet — {config.name}

**This is an infrastructure proof, not a research conclusion** (RESEARCH_METHODOLOGY
rules 3 and 7 apply before any claim is made from one configuration).

## Configuration

| | |
|---|---|
| Factor | {config.factor} v{config.factor_version} |
| Universe | {config.universe} (survivorship-free, QNT-041 gate) |
| Period | {config.start} to {config.end} |
| Rebalance | {config.rebalance.value}, offset {config.rebalance_offset} |
| Selection / weighting | top {config.top_n}, {config.weighting.value} |
| Initial capital | {initial:,.0f} GBX (£{initial / 100:,.0f}) |
| Costs | {config.commission_bps} bps commission (min {config.commission_min} GBX), \
{config.spread_bps} bps spread, {config.stamp_duty_bps} bps stamp (buys), \
impact {config.impact_coefficient_bps} bps x participation |
| Config hash | `{config.config_hash()}` |
| Git commit | `{result.git_commit}` |
| Run record | `{directory}` |

## Headline metrics

| Metric | Value |
|---|---|
| Total return | {pct(record.total_return)} |
| CAGR | {pct(record.cagr)} |
| Annualised volatility | {pct(record.annualised_volatility)} |
| Sharpe (rf = 0) | {num(record.sharpe)} |
| Sortino | {num(record.sortino)} |
| Max drawdown | {pct(record.max_drawdown)} (trough {record.max_drawdown_trough}) |
| Calmar | {num(record.calmar)} |
| Hit rate (days) | {pct(record.hit_rate_periods)} |
| Hit rate (positions) | {pct(record.hit_rate_positions)} |
| Final value | {final_value:,.0f} GBX (£{final_value / 100:,.0f}) |
| Total costs paid | {total_costs:,.0f} GBX (£{total_costs / 100:,.0f}) |
| Mean one-way turnover per rebalance | {mean_turnover:.1%} |
| Rebalances / trades | {rebalances.height} / {int(rebalances["trades"].sum())} |

## Annual returns

| Year | Return |
|---|---|
{annual_lines}

## Flags

{flags}

## Conventions and caveats

- Coverage starts 2010-01-01 (DEC-014); ~2.5% of member-months have enumerated data gaps
  (DEC-016) whose absent names are mostly acquisition exits — their missing final run-ups
  would generally have HELPED momentum, so the bias direction is conservative.
- Decisions use the previous session's knowledge; fills at the rebalance close; dividends
  credit on ex-date; unknown delistings write off (DEC-017).
- No delisting/merger records are canonicalised yet, so departures exit via DEC-019 forced
  exits at the last traded close ({forced_exits} of them; {warning_count} warnings total).
- Risk-free rate assumed zero — Sharpe is overstated until a gilt/SONIA series is ingested.
- Position construction rules per DEC-018.
- Prices/dividends/splits are the DEC-020 unit-repaired datasets (EODHD's GBX/GBP
  inconsistencies detected and normalised; evidence in unit_repair_report.json).
"""


def main() -> None:
    from trp.logging import setup_logging

    setup_logging()
    settings = load_settings()
    prices_dir = settings.canonical_dir / "prices"
    trade_dates = pl.read_parquet(prices_dir / "**/*.parquet", columns=["trade_date"])
    newest = trade_dates["trade_date"].max()
    assert isinstance(newest, date)
    config = default_ftse100_momentum_config(newest)
    result, record, directory = run(config)
    tearsheet = render_tearsheet(result, record, directory)
    target = Path("docs/tearsheets") / f"{config.name}.md"
    target.parent.mkdir(parents=True, exist_ok=True)
    if target.exists():
        raise FileExistsError(f"{target} exists; tearsheets are never overwritten")
    target.write_text(tearsheet)
    logger.info("tearsheet written to %s", target)
    print(f"run record: {directory}")
    print(f"tearsheet:  {target}")


if __name__ == "__main__":
    main()
