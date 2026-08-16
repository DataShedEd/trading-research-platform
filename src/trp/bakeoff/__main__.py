"""CLI: execute a bake-off run or subset. ``uv run python -m trp.bakeoff --help``.

Adapters register in ``_ADAPTERS`` as they land (QNT-031…033); until then the CLI can
enumerate the plan but has nothing real to call — which is itself the honest state.
"""

import argparse
import sys

from trp.bakeoff.harness import RunConfig, run_bakeoff
from trp.bakeoff.universe.loader import AwkwardProperty, Market, load_universe
from trp.config import load_settings
from trp.logging import setup_logging
from trp.providers.base import Dataset, MarketDataProvider

_ADAPTERS: dict[str, type[MarketDataProvider]] = {}  # filled by QNT-031…033


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="trp.bakeoff", description=__doc__)
    parser.add_argument("--run-id", required=True)
    parser.add_argument("--provider", action="append", dest="providers", default=[])
    parser.add_argument("--dataset", action="append", choices=[d.value for d in Dataset])
    parser.add_argument("--market", action="append", choices=[m.value for m in Market])
    parser.add_argument(
        "--property",
        action="append",
        dest="properties",
        choices=[p.value for p in AwkwardProperty],
    )
    parser.add_argument("--resume", action="store_true")
    args = parser.parse_args(argv)

    settings = load_settings()
    setup_logging(settings.log_level)

    unknown = [name for name in args.providers if name not in _ADAPTERS]
    if unknown or not args.providers:
        available = ", ".join(sorted(_ADAPTERS)) or "none yet (QNT-031…033 are blocked on API keys)"
        print(
            f"unknown or missing providers {unknown or ''}; available adapters: {available}",
            file=sys.stderr,
        )
        return 2

    config = RunConfig(
        providers=[_ADAPTERS[name]() for name in args.providers],
        universe=load_universe(),
        raw_root=settings.raw_dir,
        results_root=settings.derived_dir / "bakeoff",
        run_id=args.run_id,
        datasets=frozenset(Dataset(d) for d in args.dataset)
        if args.dataset
        else frozenset(Dataset),
        markets=frozenset(Market(m) for m in args.market) if args.market else None,
        properties=(
            frozenset(AwkwardProperty(p) for p in args.properties) if args.properties else None
        ),
        resume=args.resume,
    )
    summary = run_bakeoff(config)
    print(
        f"run {args.run_id}: {summary.cells_completed} cells completed, "
        f"{summary.cells_skipped} skipped, {summary.throttle_events} throttle events, "
        f"failures: { {k.value: v for k, v in summary.failures.items()} }"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
