"""QNT-057 gate: a persisted run record reproduces itself from its config alone, on the
real canonical store. Run with `uv run pytest -m gate`."""

import json

import polars as pl
import pytest

from trp.backtest.config import BacktestConfig
from trp.backtest.engine import BacktestEngine
from trp.backtest.rebalance import factor_strategy
from trp.backtest.runner import load_market
from trp.config import load_settings
from trp.factors.registry import FactorRegistry
from trp.universe.query import UniverseQuery

SETTINGS = load_settings()
# Newest record by write time: after a canonical re-adjudication, OLDER records
# legitimately stop reproducing (their manifests pin the prior data versions and the
# registry's rerun path reports the diff); the gate's claim is about the CURRENT store.
RUNS = sorted(
    (SETTINGS.derived_dir / "backtests").glob("*/config.json"),
    key=lambda path: path.stat().st_mtime,
)

pytestmark = [
    pytest.mark.gate,
    pytest.mark.skipif(not RUNS, reason="no persisted backtest runs"),
]


def test_latest_run_reproduces_from_its_persisted_config() -> None:
    run_dir = RUNS[-1].parent
    config = BacktestConfig.model_validate_json((run_dir / "config.json").read_text())
    meta = json.loads((run_dir / "meta.json").read_text())
    assert meta["config_hash"] == config.config_hash()  # the record is self-consistent

    market = load_market(config)
    strategy = factor_strategy(
        FactorRegistry.load().get(config.factor, version=config.factor_version), config
    )
    engine = BacktestEngine(
        config,
        market,
        UniverseQuery(SETTINGS.canonical_dir / "universes"),
        fundamentals_root=SETTINGS.canonical_dir / "fundamentals",
        fx_root=SETTINGS.canonical_dir / "fx",
        shares_root=SETTINGS.canonical_dir / "shares",
    )
    result = engine.run(strategy)

    persisted_daily = pl.read_parquet(run_dir / "daily.parquet")
    assert result.daily.equals(persisted_daily), (
        f"run {run_dir.name} does not reproduce from its own config — "
        "the store has drifted or determinism is broken"
    )
    persisted_events = pl.read_parquet(run_dir / "events.parquet")
    assert result.events.equals(persisted_events)
