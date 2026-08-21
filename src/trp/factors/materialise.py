"""Materialise factor cross-sections to the derived store (QNT-048 persistence).

Computes named factors over the survivorship-free universe at month-end sessions and
writes them via the QNT-042 never-overwrite writer, tagged with definition version,
``end``, ``as_of`` and input dataset versions — which also makes them queryable from the
SQL console / DataGrip ``factor_values`` view.

Usage::

    uv run python -m trp.factors.materialise                 # all factors, full window
    uv run python -m trp.factors.materialise qvm_equal roe   # a subset

Already-written (name, version, end) files are skipped, so reruns extend rather than
duplicate. Composites carry a ``components`` column identifying every component version.
"""

import logging
import sys
from datetime import UTC, date, datetime, time, timedelta

from trp.canonical.calendars import get_trading_calendar
from trp.canonical.price_store import read_bars
from trp.canonical.unit_repair import REPAIRED_SOURCE
from trp.config import load_settings
from trp.factors.compute import ComputeContext, compute_factor, write_factor_values
from trp.factors.definition import DefinitionError
from trp.factors.registry import FactorRegistry
from trp.universe.query import UniverseQuery

logger = logging.getLogger(__name__)

UNIVERSE = "FTSE100"
START = date(2010, 1, 1)  # DEC-014 research coverage
LOOKBACK_DAYS = 450  # bars supplied to each computation, matching the backtest context


def month_end_sessions(start: date, end: date) -> list[date]:
    sessions = get_trading_calendar("XLON").sessions_between(start, end)
    return [
        session
        for index, session in enumerate(sessions)
        if index + 1 == len(sessions) or sessions[index + 1].month != session.month
    ]


def materialise(names: list[str] | None = None) -> None:
    settings = load_settings()
    registry = FactorRegistry.load()
    definitions = [d for d in registry.definitions() if names is None or d.name in set(names)]
    if not definitions:
        raise DefinitionError(f"no definitions matched {names}")
    universe_query = UniverseQuery(settings.canonical_dir / "universes")
    derived_root = settings.derived_dir / "factors"
    prices_root = settings.canonical_dir / "prices"
    today = datetime.now(UTC).date()
    newest = max(
        bar.trade_date
        for bar in read_bars(
            prices_root, start=today - timedelta(days=40), sources=[REPAIRED_SOURCE]
        )
    )
    dates = month_end_sessions(START, newest)
    written = skipped = 0
    for end in dates:
        as_of = datetime.combine(end, time(23, 59, 59), tzinfo=UTC)
        pending = [
            d
            for d in definitions
            if not (
                derived_root / f"name={d.name}" / f"version={d.version}" / f"end={end}.parquet"
            ).exists()
        ]
        if not pending:
            skipped += len(definitions)
            continue
        members = universe_query.members(UNIVERSE, end, as_of=as_of)
        bars = read_bars(
            prices_root,
            start=end - timedelta(days=LOOKBACK_DAYS),
            end=end,
            sources=[REPAIRED_SOURCE],
            security_ids=[str(m) for m in members],
        )
        context = ComputeContext(
            security_ids=sorted(members),
            end=end,
            as_of=as_of,
            bars=bars,
            input_versions={"prices": REPAIRED_SOURCE, "universe": UNIVERSE},
            fundamentals_root=settings.canonical_dir / "fundamentals",
            fx_root=settings.canonical_dir / "fx",
            shares_root=settings.canonical_dir / "shares",
        )
        for definition in pending:
            frame = compute_factor(definition, context)
            write_factor_values(frame, derived_root)
            written += 1
        logger.info("%s: %d definitions", end, len(pending))
    logger.info("materialise: %d written, %d already present", written, skipped)


if __name__ == "__main__":
    from trp.logging import setup_logging

    setup_logging()
    materialise(sys.argv[1:] or None)
