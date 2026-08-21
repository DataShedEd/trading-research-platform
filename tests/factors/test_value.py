"""QNT-046: value factors — PIT market values, dated FX, yield-form conventions."""

from datetime import UTC, date, datetime, timedelta
from pathlib import Path

import polars as pl
import pytest

from tests.factors.test_quality import SNAPSHOT, T, context_for, records, seed, value_of
from tests.factors.test_returns import daily_bars
from trp.canonical.fundamentals.storage import write_fundamentals
from trp.domain.identifiers import SecurityId, new_security_id
from trp.factors.compute import ComputeContext


@pytest.fixture
def store(tmp_path: Path) -> Path:
    return tmp_path / "fundamentals"


@pytest.fixture
def fx_root(tmp_path: Path) -> Path:
    root = tmp_path / "fx"
    root.mkdir()
    dates = [date(2021, 1, 1) + timedelta(days=7 * i) for i in range(30)]  # weekly: never stale
    pl.DataFrame({"date": dates, "rate": [1.5] * len(dates)}).write_parquet(root / "gbpusd.parquet")
    pl.DataFrame({"date": dates, "rate": [1.25] * len(dates)}).write_parquet(
        root / "gbpeur.parquet"
    )
    return root


def market_context(
    store: Path,
    fx_root: Path,
    sid: SecurityId,
    *,
    price_gbx: str = "400",
    end: date = T,
    as_of: datetime | None = None,
) -> ComputeContext:
    base = context_for(store, sid, end=end, as_of=as_of or datetime(2021, 7, 1, tzinfo=UTC))
    bars = daily_bars(sid, date(2021, 1, 4), end, price_gbx)
    return ComputeContext(
        security_ids=base.security_ids,
        end=base.end,
        as_of=base.as_of,
        bars=bars,
        fundamentals_root=store,
        fx_root=fx_root,
    )


def seed_market(store: Path, sid: SecurityId, **overrides: str) -> None:
    """SNAPSHOT plus a share count: 1,000 shares. At 400 GBX the market cap is GBP 4,000."""
    seed(store, sid, shares_outstanding="1000", **overrides)


def test_earnings_yield_hand_case_gbx_price(store: Path, fx_root: Path) -> None:
    sid = new_security_id()
    seed_market(store, sid)  # net_income GBP 100
    row = value_of("earnings_yield", market_context(store, fx_root, sid))
    # mcap = 400 GBX / 100 x 1,000 = GBP 4,000; yield = 100 / 4,000.
    assert row["status"] == "ok"
    assert row["value"] == pytest.approx(100 / 4000)


def test_usd_reporter_converts_at_the_dated_rate(store: Path, fx_root: Path) -> None:
    sid = new_security_id()
    write_fundamentals(
        records(
            sid,
            {**SNAPSHOT, "net_income": "300", "shares_outstanding": "1000"},
            date(2020, 12, 31),
            datetime(2021, 4, 30, tzinfo=UTC),
            currency="USD",
        ),
        store,
        source="fixture",
    )
    row = value_of("earnings_yield", market_context(store, fx_root, sid))
    # USD 300 at GBPUSD 1.5 = GBP 200 over GBP 4,000.
    assert row["value"] == pytest.approx(200 / 4000)


def test_enterprise_value_yields(store: Path, fx_root: Path) -> None:
    sid = new_security_id()
    seed_market(store, sid)  # ebit 200, ebitda 250, net_debt 200 -> EV = 4,000 + 200
    ebit_row = value_of("ebit_ev_yield", market_context(store, fx_root, sid))
    assert ebit_row["value"] == pytest.approx(200 / 4200)
    ebitda_row = value_of("ebitda_ev_yield", market_context(store, fx_root, sid))
    assert ebitda_row["value"] == pytest.approx(250 / 4200)


def test_non_positive_enterprise_value_is_not_meaningful(store: Path, fx_root: Path) -> None:
    sid = new_security_id()
    seed_market(store, sid, net_debt="-5000")  # net cash swamps the market cap
    row = value_of("ebit_ev_yield", market_context(store, fx_root, sid))
    assert row["status"] == "not_meaningful"
    assert "enterprise_value" in row["warnings"][0]


def test_negative_earnings_rank_naturally_in_yield_form(store: Path, fx_root: Path) -> None:
    sid = new_security_id()
    seed_market(store, sid, net_income="-80")
    row = value_of("earnings_yield", market_context(store, fx_root, sid))
    assert row["status"] == "ok"  # a negative yield is rankable; a negative P/E is not
    assert row["value"] == pytest.approx(-80 / 4000)


def test_negative_book_value_is_excluded_not_a_number(store: Path, fx_root: Path) -> None:
    sid = new_security_id()
    seed_market(store, sid, total_equity="-50")
    row = value_of("book_to_market", market_context(store, fx_root, sid))
    assert row["status"] == "not_meaningful"
    assert row["warnings"] == ["negative book value"]


def test_book_to_market_hand_case(store: Path, fx_root: Path) -> None:
    sid = new_security_id()
    seed_market(store, sid)  # equity 500 over mcap 4,000
    row = value_of("book_to_market", market_context(store, fx_root, sid))
    assert row["value"] == pytest.approx(500 / 4000)


def test_shareholder_yield_signs(store: Path, fx_root: Path) -> None:
    buyer = new_security_id()
    seed_market(store, buyer, dividends_paid="-100", share_buybacks="-60")
    row = value_of("shareholder_yield", market_context(store, fx_root, buyer))
    assert row["value"] == pytest.approx(160 / 4000)  # cash returned is positive

    issuer = new_security_id()
    seed_market(store, issuer, dividends_paid="-100", share_buybacks="200")
    row = value_of("shareholder_yield", market_context(store, fx_root, issuer))
    assert row["value"] == pytest.approx(-100 / 4000)  # net issuance is a negative yield


def test_missing_fx_rate_is_no_data_with_the_reason(store: Path, tmp_path: Path) -> None:
    sid = new_security_id()
    write_fundamentals(
        records(
            sid,
            {**SNAPSHOT, "net_income": "300", "shares_outstanding": "1000"},
            date(2020, 12, 31),
            datetime(2021, 4, 30, tzinfo=UTC),
            currency="USD",
        ),
        store,
        source="fixture",
    )
    empty_fx = tmp_path / "fx-empty"
    empty_fx.mkdir()
    old = [date(2015, 1, 1)]
    pl.DataFrame({"date": old, "rate": [1.5]}).write_parquet(empty_fx / "gbpusd.parquet")
    pl.DataFrame({"date": old, "rate": [1.25]}).write_parquet(empty_fx / "gbpeur.parquet")
    row = value_of("earnings_yield", market_context(store, empty_fx, sid))
    assert row["status"] == "no_data"
    assert "stale" in row["warnings"][0]
