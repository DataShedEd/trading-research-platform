"""QNT-108: the synthetic-market gate — a full run whose every number was derived by
hand before the engine touched it.

Five securities (s1..s5, ids chosen so alphabetical order matches labels), XLON
calendar, 2021-01-01..2021-04-30, monthly rebalances (fills Jan 4 / Feb 1 / Mar 1 /
Apr 1, each decided on the previous session per DEC-017), the REAL factor_strategy over
the registered momentum_3_0 definition, top_n=2, equal weight, whole shares, 10 bps
commission and no other costs. Prices are flat segments that only step mid-month, so
the decision-day sizing price always equals the fill price.

PRICE PATHS (GBX)
  s1: 100 -> 140 on 2020-11-16; flat after. Pays a 7 GBX dividend ex 2021-02-15.
  s2: 100 -> 104 on 2020-11-16 -> 150 on 2021-01-15; 2-for-1 split ex 2021-03-15
      (150 -> 75 from the split date).
  s3: 100 -> 103 on 2020-11-16 -> 130 on 2021-02-12.
  s4: 200 -> 204 on 2020-11-16; flat. (Never selected; proves bystanders stay inert.)
  s5: 100 -> 101 on 2020-11-16 -> 160 on 2021-02-12; last print 2021-03-12, FAILURE
      delisting ex 2021-03-15 (announced that day) — write-off to zero, DEC-023.

3-0 MOMENTUM AT EACH DECISION (window = calendar months, endpoints on-or-before)
  Dec 31: s1 +40%   s2 +4%     s3 +3%     s4 +2%  s5 +1%   -> top2 {s1, s2}
  Jan 29: s1 +40%   s2 +50%    s3 +3%     s4 +2%  s5 +1%   -> top2 {s2, s1}, no change
  Feb 26: s1 +5.263% (140/133 via the dividend)  s2 +44.231% (150/104)
          s3 +26.214% (130/103)  s4 0%  s5 +58.416% (160/101) -> top2 {s5, s2}
  Mar 31: s2 +44.231% (split-adjusted: 75x2/104)  s3 +26.214%  s1 +5.263%  s4 0%
          s5 -100% (failure proceeds 0)                        -> top2 {s2, s3}

HAND-DERIVED LEDGER (sells first; buys alphabetical, shrunk to affordable cash;
commission = 10 bps of notional, exact decimals)
  Jan 4:  value 1,000,000 cash. Targets floor(500,000/price): s1 3571 @140
          (notional 499,940, comm 499.94), s2 4807 -> affordable 4798 @104
          (498,992, comm 498.992). Cash 69.068. Value 999,001.068.
  Feb 1:  decision value 69.068 + 3571x140 + 4798x150 = 1,219,709.068.
          Targets s1 floor(609,854.534/140)=4356, s2 floor(/150)=4065.
          SELL s2 733 @150 (109,950, comm 109.95); BUY s1 785 -> affordable 784 @140
          (109,760, comm 109.76). Cash 39.358. Value 1,219,489.358.
  Feb 15: dividend 7 x 4355 = 30,485. Cash 30,524.358. Value 1,249,974.358.
  Mar 1:  decision value 1,249,974.358. Targets s2 floor(624,987.179/150)=4166,
          s5 floor(/160)=3906. SELL s1 4355 @140 (609,700, comm 609.70);
          BUY s2 101 @150 (15,150, comm 15.15); BUY s5 3906 -> affordable 3898 @160
          (623,680, comm 623.68). Cash 145.828. Value 1,248,725.828.
  Mar 15: s2 splits 2:1 -> 8332 @75 (value unchanged); s5 write-off -3898x160 =
          -623,680. Value 625,045.828.
  Apr 1:  decision value 625,045.828. Targets s2 floor(312,522.914/75)=4166,
          s3 floor(/130)=2404. SELL s2 4166 @75 (312,450, comm 312.45);
          BUY s3 2404 -> affordable 2399 @130 (311,870, comm 311.87).
          Cash 101.508. Final value 624,421.508 through Apr 30.
  Costs: 998.932 + 219.71 + 1,248.53 + 624.32 = 3,091.492 total.

The expected ledger is persisted in golden/synthetic_market_ledger.json (written from
THIS derivation, not from engine output). Tolerances: share counts, event kinds and
dates exact; monetary floats to 1e-6 absolute (exact decimals rendered through float).
"""

import json
from datetime import UTC, date, datetime
from decimal import Decimal
from pathlib import Path

import pytest

from tests.backtest.test_engine import StubUniverse, daily_bars, make_market
from trp.backtest.config import BacktestConfig
from trp.backtest.engine import BacktestEngine
from trp.backtest.rebalance import factor_strategy
from trp.domain.corporate_actions import DelistingAction, Dividend, Split
from trp.domain.identifiers import SecurityId
from trp.domain.security import DelistingReason
from trp.factors.registry import FactorRegistry

FIXTURE = Path(__file__).parent / "golden" / "synthetic_market_ledger.json"

S1 = SecurityId("SEC-00000000-0000-4000-8000-000000000001")
S2 = SecurityId("SEC-00000000-0000-4000-8000-000000000002")
S3 = SecurityId("SEC-00000000-0000-4000-8000-000000000003")
S4 = SecurityId("SEC-00000000-0000-4000-8000-000000000004")
S5 = SecurityId("SEC-00000000-0000-4000-8000-000000000005")

KNOWN = datetime(2020, 12, 31, tzinfo=UTC)
BARS_FROM = date(2020, 9, 1)


def synthetic_market():  # type: ignore[no-untyped-def]
    end = date(2021, 4, 30)
    step = date(2020, 11, 16)
    bars = (
        daily_bars(S1, BARS_FROM, end, "100", {step: "140"})
        + daily_bars(
            S2,
            BARS_FROM,
            end,
            "100",
            {step: "104", date(2021, 1, 15): "150", date(2021, 3, 15): "75"},
        )
        + daily_bars(S3, BARS_FROM, end, "100", {step: "103", date(2021, 2, 12): "130"})
        + daily_bars(S4, BARS_FROM, end, "200", {step: "204"})
        + daily_bars(
            S5, BARS_FROM, date(2021, 3, 12), "100", {step: "101", date(2021, 2, 12): "160"}
        )
    )
    actions = [
        Dividend(
            security_id=S1,
            ex_date=date(2021, 2, 15),
            source="t",
            available_at=KNOWN,
            amount=Decimal("7"),
            currency="GBX",
        ),
        Split(
            security_id=S2,
            ex_date=date(2021, 3, 15),
            source="t",
            available_at=KNOWN,
            new_shares=2,
            old_shares=1,
        ),
        DelistingAction(
            security_id=S5,
            ex_date=date(2021, 3, 15),
            last_trading_date=date(2021, 3, 12),
            reason=DelistingReason.FAILURE,
            available_at=datetime(2021, 3, 15, tzinfo=UTC),
            available_at_imputed=False,
            source="t",
        ),
    ]
    return make_market(bars, actions)


def run_synthetic():  # type: ignore[no-untyped-def]
    config = BacktestConfig(
        name="synthetic-market-gate",
        start=date(2021, 1, 1),
        end=date(2021, 4, 30),
        universe="TEST",
        factor="momentum_3_0",
        factor_version=1,
        top_n=2,
        initial_cash=Decimal("1000000"),
        commission_bps=Decimal("10"),
        commission_min=Decimal(0),
        spread_bps=Decimal(0),
        stamp_duty_bps=Decimal(0),
        impact_coefficient_bps=Decimal(0),
    )
    strategy = factor_strategy(FactorRegistry.load().get("momentum_3_0"), config)
    engine = BacktestEngine(
        config,
        synthetic_market(),
        StubUniverse(frozenset({S1, S2, S3, S4, S5})),  # type: ignore[arg-type]
    )
    return engine.run(strategy)


@pytest.fixture(scope="module")
def result():  # type: ignore[no-untyped-def]
    return run_synthetic()


@pytest.fixture(scope="module")
def expected():  # type: ignore[no-untyped-def]
    return json.loads(FIXTURE.read_text())


def test_trade_ledger_matches_hand_derivation(result, expected) -> None:  # type: ignore[no-untyped-def]
    """Every trade, dividend, split and write-off: kind, date, security, quantity and
    cost, in execution order within each day (sells before buys, buys alphabetical)."""
    events = result.events.filter(result.events["kind"] != "deposit")
    got = [
        {
            "on": row["on"],
            "kind": row["kind"],
            "security_id": row["security_id"],
            "quantity_delta": row["quantity_delta"],
            "costs": float(row["costs"]),
        }
        for row in events.to_dicts()
    ]
    assert len(got) == len(expected["events"])
    for actual, exp in zip(got, expected["events"], strict=True):
        assert actual["on"] == exp["on"], (actual, exp)
        assert actual["kind"] == exp["kind"], (actual, exp)
        assert actual["security_id"] == exp["security_id"], (actual, exp)
        assert actual["quantity_delta"] == exp["quantity_delta"], (actual, exp)
        assert actual["costs"] == pytest.approx(exp["costs"], abs=1e-6), (actual, exp)
    # The FAILURE delisting is KNOWN-zero proceeds (DEC-023), not an unknown-terms
    # write-off: the ledger books delisting_proceeds with exactly zero cash.
    failure = events.filter(events["kind"] == "delisting_proceeds").to_dicts()
    assert len(failure) == 1 and float(failure[0]["cash_delta"]) == 0.0


def test_daily_checkpoints_match_hand_derivation(result, expected) -> None:  # type: ignore[no-untyped-def]
    daily = {str(row["date"]): row for row in result.daily.to_dicts()}
    for checkpoint in expected["daily_checkpoints"]:
        row = daily[checkpoint["date"]]
        assert row["value"] == pytest.approx(checkpoint["value"], abs=1e-6), checkpoint
        assert row["cash"] == pytest.approx(checkpoint["cash"], abs=1e-6), checkpoint
        assert row["positions"] == checkpoint["positions"], checkpoint


def test_rebalance_record_matches_hand_derivation(result, expected) -> None:  # type: ignore[no-untyped-def]
    active = result.rebalances.filter(result.rebalances["trades"] > 0)
    assert active.height == len(expected["rebalances"])
    for row, exp in zip(active.to_dicts(), expected["rebalances"], strict=True):
        assert str(row["date"]) == exp["date"]
        assert row["trades"] == exp["trades"]
        assert row["costs"] == pytest.approx(exp["costs"], abs=1e-6)
        assert row["turnover"] == pytest.approx(exp["turnover"], rel=1e-9)


def test_final_state_and_cost_identity(result, expected) -> None:  # type: ignore[no-untyped-def]
    assert result.daily["value"].to_list()[-1] == pytest.approx(expected["final_value"], abs=1e-6)
    total_costs = sum(float(c) for c in result.events["costs"].to_list())
    assert total_costs == pytest.approx(expected["total_costs"], abs=1e-6)
    # The run ends holding s2 and s3 only, with the hand-derived counts.
    assert result.daily["positions"].to_list()[-1] == 2


def test_no_warnings_everything_was_executable(result) -> None:  # type: ignore[no-untyped-def]
    """The scenario is designed so nothing is skipped, deferred or force-exited."""
    assert result.warnings == []


def test_holdings_history_replays_the_ledger(result) -> None:  # type: ignore[no-untyped-def]
    """The §13 holdings artefact reproduces the hand-derived book at each change day."""
    from trp.backtest.engine import holdings_history

    history = holdings_history(result.events)
    by_day = {
        day: {row["security_id"]: row["shares"] for row in group.to_dicts()}
        for (day,), group in history.partition_by("date", as_dict=True).items()
    }
    assert by_day["2021-01-04"] == {str(S1): 3571, str(S2): 4798}
    assert by_day["2021-02-01"] == {str(S1): 4355, str(S2): 4065}
    assert by_day["2021-03-01"] == {str(S2): 4166, str(S5): 3898}
    assert by_day["2021-03-15"] == {str(S2): 8332}
    assert by_day["2021-04-01"] == {str(S2): 4166, str(S3): 2399}
