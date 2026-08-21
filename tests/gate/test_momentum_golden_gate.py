"""QNT-107 gate: golden 12-1 momentum observations on the real dataset.

THE CONVENTION (the single documented statement — docs/RESEARCH_METHODOLOGY.md links
here): 12-1 momentum at observation date t is the cumulative TOTAL return over the
window [t - 12 calendar months, t - 1 calendar month]:

- **Windows are calendar months, not observation counts** (never "21/252 trading
  days"): endpoints come from ``shift_months`` (clamping to the target month's last
  day), each resolved to the last bar ON OR BEFORE the endpoint, no more than 15
  calendar days older, else INSUFFICIENT_DATA.
- **Total return** = split- and dividend-adjusted under the reinvestment convention:
  each dividend reinvested at its ex-date, i.e. every pre-ex value is scaled by
  ``(1 - D/P_prev)`` where ``P_prev`` is the raw close on the last bar before the
  ex-date (post-split when a split shares the ex-date). Dividends are aligned to the
  GBX quote unit first.
- **Coverage floor**: the window must contain >= 60% of the exchange calendar's
  sessions between the resolved endpoints, else INSUFFICIENT_DATA. Nothing is
  forward-filled across a delisting; a delisted name returns through known proceeds or
  the typed DELISTED_NO_PROCEEDS.
- **Point in time**: as_of = 23:59:59 UTC on t; membership from the PIT universe with
  that as_of; only actions with available_at <= as_of participate.

WHAT THIS GATE PROVES (beyond the production function agreeing with itself): for four
historical dates — early, mid-period, COVID-stressed, recent — securities drawn from
the top, middle and bottom of the ranking are re-derived by the INDEPENDENT
implementation below, which reads the canonical parquet files directly and applies the
textbook formula

    ret = (P_e / P_s) * prod[splits s<ex<=e](new/old) / prod[divs s<ex<=e](1 - D/P_prev) - 1

with none of the trp.factors machinery. Production must agree to 1e-9 relative. The
full ranked cross-sections are pinned in golden/momentum_12_1_goldens.json — regenerate
deliberately with `uv run python tests/gate/test_momentum_golden_gate.py regen` after a
documented data correction, never to make a red gate green.

The fixture answers "why was this security ranked #7?": membership evidence, both
endpoint bars, every corporate action inside the window, the computed return, the rank
and the missing-data treatment are all recorded per inspected security.
"""

import json
from datetime import UTC, date, datetime, time, timedelta
from pathlib import Path

import polars as pl
import pytest

from trp.backtest.context import computable_inputs
from trp.backtest.runner import load_actions
from trp.canonical.price_store import read_bars
from trp.canonical.unit_repair import DIVIDENDS_FILE, REPAIRED_SOURCE, SPLITS_FILE
from trp.config import load_settings
from trp.factors.compute import ComputeContext, compute_factor
from trp.factors.materialise import month_end_sessions
from trp.factors.registry import FactorRegistry
from trp.universe.query import UniverseQuery

pytestmark = pytest.mark.gate

SETTINGS = load_settings()
FIXTURE = Path(__file__).parent / "golden" / "momentum_12_1_goldens.json"
LOOKBACK_DAYS = 450
STALENESS_DAYS = 15
PREV_CLOSE_GAP_DAYS = 7

GOLDEN_DATES = [
    date(2011, 6, 30),  # early: first full year of DEC-014 coverage
    date(2015, 6, 30),  # mid-period
    date(2020, 3, 31),  # stressed: COVID crash month end
    date(2025, 6, 30),  # recent
]


# --------------------------------------------------------------------- production path
def production_cross_section(end: date, universe: str = "FTSE100") -> pl.DataFrame:
    """Exactly the materialise/backtest assembly: PIT members, repaired bars over the
    lookback, the computable slice of repaired actions, the registered definition."""
    as_of = datetime.combine(end, time(23, 59, 59), tzinfo=UTC)
    members = UniverseQuery(SETTINGS.canonical_dir / "universes").members(
        universe, end, as_of=as_of
    )
    bars = read_bars(
        SETTINGS.canonical_dir / "prices",
        start=end - timedelta(days=LOOKBACK_DAYS),
        end=end,
        sources=[REPAIRED_SOURCE],
        security_ids=[str(m) for m in members],
    )
    actions, _ = load_actions(SETTINGS.canonical_dir / "corporate_actions")
    member_set = set(members)
    bars, sliced = computable_inputs(
        list(bars), [a for a in actions if a.security_id in member_set]
    )
    context = ComputeContext(
        security_ids=sorted(members), end=end, as_of=as_of, bars=bars, actions=sliced
    )
    frame = compute_factor(FactorRegistry.load().get("momentum_12_1"), context)
    ranked = (
        frame.select("security_id", "status", "value")
        .with_columns(
            pl.col("value")
            .rank(descending=True, method="ordinal")
            .over(pl.col("status") == "ok")
            .alias("rank")
        )
        .with_columns(
            pl.when(pl.col("status") == "ok").then(pl.col("rank")).otherwise(None).alias("rank")
        )
        .sort("rank", nulls_last=True)
    )
    return ranked


# ------------------------------------------------------------------- independent path
def shift_months_simple(day: date, months: int) -> date:
    """Calendar-month shift clamping to month end — reimplemented, not imported."""
    index = day.year * 12 + day.month - 1 + months
    year, month0 = divmod(index, 12)
    month = month0 + 1
    next_month_start = date(year + (month == 12), 1 if month == 12 else month + 1, 1)
    last_day = (next_month_start - timedelta(days=1)).day
    return date(year, month, min(day.day, last_day))


def independent_momentum(security_id: str, end: date) -> dict:  # type: ignore[type-arg]
    """The textbook formula straight off the canonical parquet files."""
    prices = (
        pl.read_parquet(
            SETTINGS.canonical_dir / "prices" / "*/part-*.parquet",
            columns=["security_id", "trade_date", "close", "source"],
        )
        .filter((pl.col("security_id") == security_id) & (pl.col("source") == REPAIRED_SOURCE))
        .sort("trade_date")
    )
    as_of = datetime.combine(end, time(23, 59, 59), tzinfo=UTC)
    actions_dir = SETTINGS.canonical_dir / "corporate_actions"
    dividends = pl.read_parquet(actions_dir / DIVIDENDS_FILE).filter(
        (pl.col("security_id") == security_id) & (pl.col("available_at") <= as_of)
    )
    splits = pl.read_parquet(actions_dir / SPLITS_FILE).filter(
        (pl.col("security_id") == security_id) & (pl.col("available_at") <= as_of)
    )

    def bar_on_or_before(target: date) -> tuple[date, float] | None:
        window = prices.filter(pl.col("trade_date") <= target)
        if window.is_empty():
            return None
        row = window.row(-1, named=True)
        if (target - row["trade_date"]).days > STALENESS_DAYS:
            return None
        return row["trade_date"], float(row["close"])

    start = bar_on_or_before(shift_months_simple(end, -12))
    finish = bar_on_or_before(shift_months_simple(end, -1))
    if start is None or finish is None:
        return {"status": "insufficient_data", "value": None}
    (s_date, s_close), (e_date, e_close) = start, finish

    ratio = e_close / s_close
    window_splits = splits.filter((pl.col("ex_date") > s_date) & (pl.col("ex_date") <= e_date))
    for split in window_splits.iter_rows(named=True):
        ratio *= split["new_shares"] / split["old_shares"]

    window_divs = dividends.filter((pl.col("ex_date") > s_date) & (pl.col("ex_date") <= e_date))
    used_actions = []
    for div in window_divs.iter_rows(named=True):
        amount = float(div["amount"])
        if div["currency"] == "GBP":
            amount *= 100.0
        elif div["currency"] != "GBX":
            continue  # engine excludes unalignable currencies from total returns
        prev = prices.filter(pl.col("trade_date") < div["ex_date"])
        if prev.is_empty():
            return {"status": "insufficient_data", "value": None}
        prev_row = prev.row(-1, named=True)
        if (div["ex_date"] - prev_row["trade_date"]).days > PREV_CLOSE_GAP_DAYS:
            return {"status": "insufficient_data", "value": None}
        prev_close = float(prev_row["close"])
        same_day = window_splits.filter(pl.col("ex_date") == div["ex_date"])
        for split in same_day.iter_rows(named=True):
            prev_close *= split["new_shares"] / split["old_shares"]  # post-split terms
        ratio /= 1.0 - amount / prev_close
        used_actions.append(
            {"kind": "dividend", "ex_date": str(div["ex_date"]), "amount_gbx": amount}
        )
    for split in window_splits.iter_rows(named=True):
        used_actions.append(
            {
                "kind": "split",
                "ex_date": str(split["ex_date"]),
                "ratio": f"{split['new_shares']}:{split['old_shares']}",
            }
        )
    return {
        "status": "ok",
        "value": ratio - 1.0,
        "start_bar": str(s_date),
        "start_close_gbx": s_close,
        "end_bar": str(e_date),
        "end_close_gbx": e_close,
        "actions_in_window": used_actions,
    }


# --------------------------------------------------------------------------- fixtures
def names_by_id() -> dict[str, str]:
    frame = pl.read_parquet(SETTINGS.canonical_dir / "securities" / "securities.parquet")
    return dict(frame.select("security_id", "name").rows())


def inspection_picks(ranked: pl.DataFrame) -> list[str]:
    """Top, middle and bottom of the OK ranking, plus one non-OK case where present."""
    ok = ranked.filter(pl.col("status") == "ok").sort("rank")
    picks = [ok.row(0, named=True), ok.row(ok.height // 2, named=True), ok.row(-1, named=True)]
    not_ok = ranked.filter(pl.col("status") != "ok")
    if not_ok.height:
        picks.append(not_ok.row(0, named=True))
    return [p["security_id"] for p in picks]


def build_goldens() -> dict:  # type: ignore[type-arg]
    names = names_by_id()
    goldens: dict = {}  # type: ignore[type-arg]
    for end in GOLDEN_DATES:
        ranked = production_cross_section(end)
        inspected = {}
        for sid in inspection_picks(ranked):
            production = ranked.filter(pl.col("security_id") == sid).row(0, named=True)
            evidence = independent_momentum(sid, end)
            inspected[sid] = {
                "name": names.get(sid, "?"),
                "member_on_date": True,  # by construction: the cross-section is PIT members
                "production_status": production["status"],
                "production_value": production["value"],
                "cross_sectional_rank": production["rank"],
                "independent": evidence,
            }
        goldens[str(end)] = {
            "cross_section": [
                {**row, "name": names.get(row["security_id"], "?")} for row in ranked.to_dicts()
            ],
            "inspected": inspected,
        }
    return goldens


# ------------------------------------------------------------------------------ tests
def test_golden_dates_are_month_end_sessions() -> None:
    sessions = set(month_end_sessions(date(2010, 1, 1), date(2026, 1, 1)))
    for day in GOLDEN_DATES[:3]:
        assert day in sessions
    assert GOLDEN_DATES[3] in set(month_end_sessions(date(2025, 1, 1), date(2026, 8, 1)))


@pytest.mark.parametrize("end", GOLDEN_DATES, ids=str)
def test_production_matches_pinned_golden_cross_section(end: date) -> None:
    goldens = json.loads(FIXTURE.read_text())[str(end)]
    ranked = production_cross_section(end)
    pinned = pl.DataFrame(goldens["cross_section"]).drop("name")
    assert ranked.height == pinned.height
    for got, expected in zip(ranked.to_dicts(), pinned.to_dicts(), strict=True):
        assert got["security_id"] == expected["security_id"]
        assert got["status"] == expected["status"]
        assert got["rank"] == expected["rank"]
        if expected["value"] is None:
            assert got["value"] is None
        else:
            assert got["value"] == pytest.approx(expected["value"], rel=1e-12)


@pytest.mark.parametrize("end", GOLDEN_DATES, ids=str)
def test_independent_reconstruction_agrees_with_production(end: date) -> None:
    """Not self-agreement: the textbook formula over raw parquet vs the full machinery."""
    goldens = json.loads(FIXTURE.read_text())[str(end)]
    checked = 0
    for sid, pinned in goldens["inspected"].items():
        fresh = independent_momentum(sid, end)
        assert fresh["status"] == pinned["production_status"] or (
            # the independent implementation has no delisting-proceeds arm; a typed
            # non-ok production status just needs the independent path to also miss data
            pinned["production_status"] != "ok" and fresh["status"] != "ok"
        )
        if pinned["production_status"] == "ok":
            assert fresh["value"] == pytest.approx(pinned["production_value"], rel=1e-9)
            checked += 1
    assert checked >= 3  # top, middle and bottom of the ranking all verified


def test_fixture_answers_why_ranked_n() -> None:
    """The evidence pack is complete for every inspected security."""
    goldens = json.loads(FIXTURE.read_text())
    for day, payload in goldens.items():
        for sid, item in payload["inspected"].items():
            assert item["name"] != "?", (day, sid)
            if item["production_status"] == "ok":
                evidence = item["independent"]
                for key in ("start_bar", "end_bar", "start_close_gbx", "end_close_gbx"):
                    assert evidence[key] is not None, (day, sid, key)
                assert item["cross_sectional_rank"] >= 1


if __name__ == "__main__":
    import sys

    if sys.argv[1:] == ["regen"]:
        FIXTURE.parent.mkdir(exist_ok=True)
        FIXTURE.write_text(json.dumps(build_goldens(), indent=1))
        print(f"wrote {FIXTURE}")
    else:
        print("usage: python tests/gate/test_momentum_golden_gate.py regen")
