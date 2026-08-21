"""QNT-045/046 timetravel: fundamental factor values at t are functions of what was
knowable at t — later prices, filings, restatements and share-count revisions are inert,
and enterprise value uses the balance sheet available at t even when a newer one exists."""

# ruff: noqa: F811 - pytest fixtures are imported by name and reused as parameters

from datetime import UTC, date, datetime

import pytest

from tests.factors.test_quality import SNAPSHOT, records, seed, value_of
from tests.factors.test_returns import daily_bars
from tests.factors.test_value import fx_root, market_context, seed_market, store  # noqa: F401
from trp.canonical.fundamentals.storage import write_fundamentals
from trp.domain.identifiers import new_security_id
from trp.factors.compute import ComputeContext

pytestmark = pytest.mark.timetravel

T = date(2021, 6, 30)


def test_prices_after_t_do_not_change_a_value_factor(store, fx_root) -> None:  # type: ignore[no-untyped-def]
    sid = new_security_id()
    seed_market(store, sid)
    clean = value_of("earnings_yield", market_context(store, fx_root, sid))
    polluted_context = market_context(store, fx_root, sid)
    future_bars = daily_bars(sid, date(2021, 7, 1), date(2021, 12, 31), "9999")
    polluted = ComputeContext(
        security_ids=polluted_context.security_ids,
        end=polluted_context.end,
        as_of=polluted_context.as_of,
        bars=list(polluted_context.bars) + future_bars,
        fundamentals_root=store,
        fx_root=fx_root,
    )
    from trp.factors.compute import compute_factor
    from trp.factors.registry import FactorRegistry

    frame = compute_factor(FactorRegistry.load().get("earnings_yield"), polluted)
    assert frame.to_dicts()[0]["value"] == pytest.approx(clean["value"])


def test_filings_knowable_after_t_are_inert(store, fx_root) -> None:  # type: ignore[no-untyped-def]
    sid = new_security_id()
    seed_market(store, sid)  # FY2020, knowable April 2021
    write_fundamentals(  # FY2021 blowout year, knowable only in 2022
        records(
            sid,
            {**SNAPSHOT, "net_income": "999", "shares_outstanding": "1000"},
            date(2021, 12, 31),
            datetime(2022, 4, 30, tzinfo=UTC),
        ),
        store,
        source="fixture",
    )
    row = value_of("earnings_yield", market_context(store, fx_root, sid))
    assert row["value"] == pytest.approx(100 / 4000)  # still the FY2020 knowledge


def test_share_count_revision_after_t_does_not_rewrite_history(store, fx_root) -> None:  # type: ignore[no-untyped-def]
    sid = new_security_id()
    seed_market(store, sid)  # 1,000 shares as originally filed
    write_fundamentals(  # restated to 2,000 shares, knowable September 2021
        records(
            sid,
            {"shares_outstanding": "2000"},
            date(2020, 12, 31),
            datetime(2021, 9, 30, tzinfo=UTC),
            revision=1,
        ),
        store,
        source="fixture",
    )
    at_t = value_of("earnings_yield", market_context(store, fx_root, sid))
    assert at_t["value"] == pytest.approx(100 / 4000)  # the original 1,000 shares
    later = value_of(
        "earnings_yield",
        market_context(
            store, fx_root, sid, end=date(2021, 10, 29), as_of=datetime(2021, 10, 29, tzinfo=UTC)
        ),
    )
    assert later["value"] == pytest.approx(100 / 8000)  # revision applies only once knowable


def test_enterprise_value_uses_the_balance_sheet_available_at_t(store, fx_root) -> None:  # type: ignore[no-untyped-def]
    sid = new_security_id()
    seed_market(store, sid)  # net_debt 200, knowable April 2021
    write_fundamentals(  # a newer balance sheet exists in the FIXTURE but not at t
        records(
            sid,
            {**SNAPSHOT, "net_debt": "4000", "shares_outstanding": "1000"},
            date(2021, 6, 30),
            datetime(2021, 10, 30, tzinfo=UTC),
        ),
        store,
        source="fixture",
    )
    row = value_of("ebit_ev_yield", market_context(store, fx_root, sid))
    assert row["value"] == pytest.approx(200 / 4200)  # EV built on the stale-but-knowable 200


def test_quality_factor_ignores_restatement_until_knowable(store) -> None:  # type: ignore[no-untyped-def]
    sid = new_security_id()
    seed(store, sid)
    write_fundamentals(
        records(
            sid,
            {"net_income": "10"},
            date(2020, 12, 31),
            datetime(2022, 1, 31, tzinfo=UTC),
            revision=1,
        ),
        store,
        source="fixture",
    )
    from tests.factors.test_quality import context_for

    at_t = value_of("roe", context_for(store, sid))
    assert at_t["value"] == pytest.approx(100 / 500)
