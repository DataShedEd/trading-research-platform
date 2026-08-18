"""QNT-057: the as-of monotonicity and restatement properties, expressed differentially.

Monotonicity is the strongest single statement the platform makes about itself: a
backtest's results are a function of information available at the simulated dates and of
nothing else. It needs no expected values — run against the restricted store, run against
the extended store, assert equality.
"""

from datetime import UTC, date, datetime
from decimal import Decimal

import pytest

from tests.backtest.test_engine import (
    A,
    B,
    daily_bars,
    make_config,
    make_market,
    run_engine,
)
from trp.backtest.context import BacktestContext
from trp.domain.corporate_actions import Dividend
from trp.factors.registry import FactorRegistry

pytestmark = pytest.mark.timetravel

END = date(2021, 6, 30)
DEFINITION = FactorRegistry.load().get("momentum_3_0")


def momentum_top1(context: BacktestContext, positions: dict, value: Decimal) -> dict:  # type: ignore[type-arg]
    frame = context.factor_values(DEFINITION, frozenset({A, B}))
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


def world(extra_bars: list | None = None, extra_actions: list | None = None):  # type: ignore[type-arg, no-untyped-def]
    bars = daily_bars(A, date(2020, 6, 1), END, "100", {date(2021, 2, 1): "104"}) + daily_bars(
        B, date(2020, 6, 1), END, "200", {date(2021, 4, 1): "212"}
    )
    return make_market(bars + (extra_bars or []), extra_actions or [])


def test_as_of_monotonicity_data_after_the_run_changes_nothing() -> None:
    """Byte-identical results when the store is extended with anything dated (or
    knowable) only after the run's end — bars, actions, the lot."""
    clean = run_engine(make_config(), world(), momentum_top1)
    extended = run_engine(
        make_config(),
        world(
            extra_bars=daily_bars(A, date(2021, 7, 1), date(2021, 12, 31), "1")
            + daily_bars(B, date(2021, 7, 1), date(2021, 12, 31), "999"),
            extra_actions=[
                Dividend(
                    security_id=A,
                    ex_date=date(2021, 5, 4),
                    source="t",
                    available_at=datetime(2021, 8, 1, tzinfo=UTC),  # knowable after END
                    amount=Decimal("50"),
                    currency="GBX",
                )
            ],
        ),
        momentum_top1,
    )
    assert clean.daily.equals(extended.daily)
    assert clean.events.equals(extended.events)
    assert clean.rebalances.equals(extended.rebalances)


def test_restatement_changes_only_rebalances_after_its_available_at() -> None:
    """A dividend restated (published) mid-run on 1 April: every daily value and every
    ledger event BEFORE the publication instant is identical; only decisions taken with
    post-publication knowledge may differ — and here they genuinely do."""
    publication = datetime(2021, 4, 1, 8, 0, tzinfo=UTC)
    restated = Dividend(
        security_id=A,
        ex_date=date(2021, 3, 8),  # inside the momentum window when published
        source="t",
        available_at=publication,
        amount=Decimal("30"),
        currency="GBX",
    )
    original = run_engine(make_config(), world(), momentum_top1)
    with_restatement = run_engine(make_config(), world(extra_actions=[restated]), momentum_top1)

    boundary = publication.date()
    before_original = original.daily.filter(original.daily["date"] < boundary)
    before_restated = with_restatement.daily.filter(with_restatement.daily["date"] < boundary)
    assert before_original.equals(before_restated)  # history is never rewritten
    events_before = original.events.filter(original.events["on"] < boundary.isoformat())
    restated_events_before = with_restatement.events.filter(
        with_restatement.events["on"] < boundary.isoformat()
    )
    assert events_before.equals(restated_events_before)
    # ...and the restatement is not inert: knowledge-bearing rebalances differ after it.
    assert not original.daily.equals(with_restatement.daily)
