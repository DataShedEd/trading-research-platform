"""QNT-109: future-data invariance per data class, at the backtest level.

The combined invariance test (test_backtest_leakage) extends the store with everything
at once; these tests extend ONE class at a time so a regression names its class. The
claim under test, per class: a historical experiment through T is bit-identical when the
dataset later gains

- future price bars                       (test_class_future_price_bars_only)
- future corporate actions, both future-dated and late-published
                                          (test_class_future_corporate_actions_only)
- later lifecycle/security-master knowledge — a delisting recorded after T
                                          (test_class_later_lifecycle_knowledge)
- future universe membership information — a spell recorded after T
                                          (test_class_future_universe_membership)
- later fundamental observations and revisions
                                          (test_class_later_fundamental_observations)

Identifier-resolution knowledge itself (ticker reuse, renames) is enforced upstream of
the engine — the master resolves to immutable SecurityIds before a backtest sees data —
and is covered by tests/timetravel/test_security_master_pit.py and tests/lifecycle/.
Bit-identity here means polars frame equality over the daily ledger, the event log and
the rebalance record — the full persisted result.
"""

# ruff: noqa: F811 - pytest fixtures are imported by name and reused as parameters

from datetime import UTC, date, datetime
from decimal import Decimal
from pathlib import Path

import pytest

from tests.backtest.test_engine import (
    A,
    B,
    C,
    daily_bars,
    make_config,
    run_engine,
)
from tests.factors.test_quality import SNAPSHOT, records
from tests.factors.test_value import fx_root  # noqa: F401
from tests.timetravel.test_backtest_leakage import END, momentum_top1, world
from trp.backtest.config import BacktestConfig
from trp.backtest.context import BacktestContext
from trp.backtest.engine import BacktestEngine, MarketData
from trp.canonical.fundamentals.storage import write_fundamentals
from trp.domain.corporate_actions import DelistingAction, Split
from trp.domain.security import DelistingReason
from trp.factors.registry import FactorRegistry
from trp.universe.membership import UniverseMembership
from trp.universe.query import UniverseQuery
from trp.universe.storage import write_universe

pytestmark = pytest.mark.timetravel


def assert_bit_identical(clean, extended) -> None:  # type: ignore[no-untyped-def]
    assert clean.daily.equals(extended.daily)
    assert clean.events.equals(extended.events)
    assert clean.rebalances.equals(extended.rebalances)


def test_class_future_price_bars_only() -> None:
    clean = run_engine(make_config(), world(), momentum_top1)
    extended = run_engine(
        make_config(),
        world(
            extra_bars=daily_bars(A, date(2021, 7, 1), date(2021, 12, 31), "1")
            + daily_bars(B, date(2021, 7, 1), date(2021, 12, 31), "999")
        ),
        momentum_top1,
    )
    assert_bit_identical(clean, extended)


def test_class_future_corporate_actions_only() -> None:
    from trp.domain.corporate_actions import Dividend

    clean = run_engine(make_config(), world(), momentum_top1)
    extended = run_engine(
        make_config(),
        world(
            extra_actions=[
                # Future-dated: announced and effective after T.
                Split(
                    security_id=A,
                    ex_date=date(2021, 9, 1),
                    source="t",
                    available_at=datetime(2021, 8, 15, tzinfo=UTC),
                    new_shares=2,
                    old_shares=1,
                ),
                # Late-published: ex-date inside the run, knowable only after T.
                Dividend(
                    security_id=B,
                    ex_date=date(2021, 3, 1),
                    source="t",
                    available_at=datetime(2021, 8, 1, tzinfo=UTC),
                    amount=Decimal("75"),
                    currency="GBX",
                ),
            ]
        ),
        momentum_top1,
    )
    assert_bit_identical(clean, extended)


def test_class_later_lifecycle_knowledge() -> None:
    """The database later learns B was delisted (a lifecycle/security-master fact
    recorded after T). DEC-017: an action applies on max(ex_date, knowable date), so
    knowledge acquired after T must be inert — no retroactive exit, no mark change."""
    clean = run_engine(make_config(), world(), momentum_top1)
    extended = run_engine(
        make_config(),
        world(
            extra_actions=[
                DelistingAction(
                    security_id=B,
                    ex_date=date(2021, 5, 3),
                    last_trading_date=date(2021, 4, 30),
                    reason=DelistingReason.UNKNOWN,
                    available_at=datetime(2021, 9, 1, tzinfo=UTC),
                    available_at_imputed=True,
                    source="lifecycle-late",
                )
            ]
        ),
        momentum_top1,
    )
    assert_bit_identical(clean, extended)


def hold_all_members(context: BacktestContext, positions: dict, value: Decimal) -> dict:  # type: ignore[type-arg]
    members = sorted(context.members())
    if not members:
        return {}
    per_name = value / len(members)
    targets = {}
    for sid in members:
        price = context.price(sid)
        if price:
            targets[sid] = int(per_name / price)
    return targets


def test_class_future_universe_membership(tmp_path: Path) -> None:
    """A membership spell recorded after T (vendor backfill, index correction) must not
    change a run through T, even though the spell's event-time range covers the run.
    C's bars sit in the market in BOTH runs — only the knowledge of its membership
    arrives late."""

    def universe_store(root: Path, *, with_backfill: bool) -> UniverseQuery:
        spells = [
            UniverseMembership(
                universe="FTSE100",
                security_id=sid,
                valid_from=date(2001, 3, 1),
                source="test-fixture",
            )
            for sid in (A, B)
        ]
        if with_backfill:
            spells.append(
                UniverseMembership(
                    universe="FTSE100",
                    security_id=C,
                    valid_from=date(2021, 2, 1),  # event time inside the run...
                    source="test-fixture",
                    recorded_at=datetime(2021, 9, 1, tzinfo=UTC),  # ...knowable after T
                )
            )
        root.mkdir()
        write_universe(spells, root, known_security_ids={A, B, C})
        return UniverseQuery(root)

    config = make_config(universe="FTSE100")
    market = world(extra_bars=daily_bars(C, date(2020, 6, 1), END, "400"))

    def run(query: UniverseQuery):  # type: ignore[no-untyped-def]
        return BacktestEngine(config, market, query).run(hold_all_members)

    clean = run(universe_store(tmp_path / "clean", with_backfill=False))
    assert clean.events.height > 0  # membership genuinely drove trades
    extended = run(universe_store(tmp_path / "extended", with_backfill=True))
    assert_bit_identical(clean, extended)


def test_class_later_fundamental_observations(tmp_path: Path, fx_root: Path) -> None:  # type: ignore[no-untyped-def]
    """A backtest whose strategy scores on fundamentals (roe) is bit-identical when the
    fundamentals store later gains a future filing AND a restatement of an in-window
    period whose available_at falls after T."""
    roe = FactorRegistry.load().get("roe")
    store = tmp_path / "fundamentals"

    def seed(root: Path) -> None:
        for sid, income in ((A, "80"), (B, "200")):
            for year in (2018, 2019, 2020):
                write_fundamentals(
                    records(
                        sid,
                        {**SNAPSHOT, "net_income": income, "shares_outstanding": "1000"},
                        date(year, 12, 31),
                        datetime(year + 1, 4, 30, tzinfo=UTC),
                    ),
                    root,
                    source="fixture",
                )

    def roe_top1(context: BacktestContext, positions: dict, value: Decimal) -> dict:  # type: ignore[type-arg]
        frame = context.factor_values(roe, frozenset({A, B}))
        scored = {
            row["security_id"]: row["value"]
            for row in frame.to_dicts()
            if row["status"] == "ok" and row["value"] is not None
        }
        if not scored:
            return {}
        best = max(sorted(scored), key=lambda s: scored[s])
        price = context.price(best)  # type: ignore[arg-type]
        return {best: int(value / price)} if price else {}

    def run(config: BacktestConfig, market: MarketData):  # type: ignore[no-untyped-def]
        from tests.backtest.test_engine import StubUniverse

        engine = BacktestEngine(
            config,
            market,
            StubUniverse(frozenset({A, B})),  # type: ignore[arg-type]
            fundamentals_root=store,
            fx_root=fx_root,
        )
        return engine.run(roe_top1)

    seed(store)
    clean = run(make_config(), world())
    assert clean.events.height > 0  # fundamentals genuinely drove selection

    # The store later learns more: a future filing and a restatement of FY2020
    # (in-window period) published after T. Same store root, extended in place.
    for sid in (A, B):
        write_fundamentals(
            records(
                sid,
                {**SNAPSHOT, "net_income": "9999", "shares_outstanding": "1"},
                date(2021, 12, 31),
                datetime(2022, 4, 30, tzinfo=UTC),
            ),
            store,
            source="fixture",
        )
    write_fundamentals(
        records(
            B,
            {"net_income": "1"},
            date(2020, 12, 31),
            datetime(2021, 9, 30, tzinfo=UTC),  # after END
            revision=1,
        ),
        store,
        source="fixture",
    )
    extended = run(make_config(), world())
    assert_bit_identical(clean, extended)
    assert date(2021, 6, 30) == END  # documents T for the docstrings above
