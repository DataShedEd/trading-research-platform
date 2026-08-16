"""Hand-computed adjustment fixtures. Every expected value below was derived on paper
from the stated event, never copied from the implementation's output.
"""

from datetime import UTC, date, datetime
from decimal import Decimal
from fractions import Fraction
from pathlib import Path

import polars as pl
import pytest

from trp.derived.adjustments import (
    AdjustmentError,
    adjusted_prices,
    compute_adjustment_factors,
    factors_to_float_frame,
    reconcile_provider_adjusted,
    total_returns,
    write_adjustment_factors,
)
from trp.domain.corporate_actions import Dividend, RightsIssue, Split
from trp.domain.identifiers import SecurityId, new_security_id
from trp.domain.prices import DailyBar

AS_OF = datetime(2021, 1, 1, tzinfo=UTC)
INGESTED = datetime(2020, 12, 31, 18, 0, tzinfo=UTC)
D1, D2, D3 = date(2020, 3, 2), date(2020, 3, 3), date(2020, 3, 4)


def bar(security_id: SecurityId, trade_date: date, close: str, **overrides: object) -> DailyBar:
    price = Decimal(close)
    fields: dict[str, object] = {
        "security_id": security_id,
        "trade_date": trade_date,
        "open": price,
        "high": price,
        "low": price,
        "close": price,
        "volume": 1000,
        "currency": "GBX",
        "source": "test",
        "ingested_at": INGESTED,
    }
    fields.update(overrides)
    return DailyBar(**fields)  # type: ignore[arg-type]


class TestSplitTwoForOne:
    """Prev close 100; 2-for-1 split ex D2; closes 100, 50, 52.
    Hand-derived: split factor before ex = old/new = 1/2; adjusted 50, 50, 52;
    return across ex-date = 0; D3 return = 52/50 - 1 = 4%."""

    def setup_method(self) -> None:
        self.sid = new_security_id()
        self.bars = [bar(self.sid, D1, "100"), bar(self.sid, D2, "50"), bar(self.sid, D3, "52")]
        self.split = Split(
            security_id=self.sid,
            ex_date=D2,
            source="test",
            available_at=AS_OF,
            new_shares=2,
            old_shares=1,
        )

    def test_factors_and_returns(self) -> None:
        computation = compute_adjustment_factors(self.bars, [self.split], as_of=AS_OF)
        assert computation.exact[(self.sid, D1)] == (Fraction(1, 2), Fraction(1))
        assert computation.exact[(self.sid, D3)] == (Fraction(1), Fraction(1))  # latest = 1

        adjusted = adjusted_prices(self.bars, computation)
        assert adjusted["close_split_adjusted"].to_list() == [
            Decimal("50"),
            Decimal("50"),
            Decimal("52"),
        ]
        returns = total_returns(self.bars, computation)["total_return"].to_list()
        assert returns[0] == Decimal("0")
        assert returns[1] == Decimal("0.04")

    def test_raw_bars_untouched(self) -> None:
        before = [b.model_dump() for b in self.bars]
        compute_adjustment_factors(self.bars, [self.split], as_of=AS_OF)
        assert [b.model_dump() for b in self.bars] == before


def test_one_for_five_consolidation_is_exact() -> None:
    """Prev close 10; 1-for-5 consolidation ex D2, close 50.
    Hand-derived: factor before ex = old/new = 5, exactly."""
    sid = new_security_id()
    bars = [bar(sid, D1, "10"), bar(sid, D2, "50")]
    consolidation = Split(
        security_id=sid,
        ex_date=D2,
        source="test",
        available_at=AS_OF,
        new_shares=1,
        old_shares=5,
    )
    computation = compute_adjustment_factors(bars, [consolidation], as_of=AS_OF)
    assert computation.exact[(sid, D1)][0] == Fraction(5, 1)  # exact, not 4.999…
    d1_row = next(r for r in computation.factors.to_dicts() if r["trade_date"] == D1)
    assert (d1_row["split_num"], d1_row["split_den"]) == (5, 1)  # exactness survives storage


class TestOrdinaryAndSpecialDividends:
    """Prev close 200; dividend 10 ex D2; closes 200, 190, 195.
    Hand-derived: dividend factor before ex = 1 - 10/200 = 19/20; total return across
    ex = 190/(200 x 19/20) - 1 = 0; price return = -5%; difference = the 5% yield."""

    def build(self, special: bool) -> tuple[SecurityId, list[DailyBar], Dividend]:
        sid = new_security_id()
        bars = [bar(sid, D1, "200"), bar(sid, D2, "190"), bar(sid, D3, "195")]
        dividend = Dividend(
            security_id=sid,
            ex_date=D2,
            source="test",
            available_at=AS_OF,
            amount=Decimal("10"),
            currency="GBX",
            special=special,
        )
        return sid, bars, dividend

    def test_price_and_total_return_differ_by_exactly_the_yield(self) -> None:
        sid, bars, dividend = self.build(special=False)
        computation = compute_adjustment_factors(bars, [dividend], as_of=AS_OF)
        assert computation.exact[(sid, D1)][1] == Fraction(19, 20)

        total = total_returns(bars, computation)["total_return"].to_list()[0]
        assert total == Decimal("0")
        price_return = Fraction(Decimal("190")) / Fraction(Decimal("200")) - 1
        assert price_return == Fraction(-1, 20)  # -5% = the dividend yield, exactly

    def test_special_dividend_same_path_flagged_in_provenance(self) -> None:
        sid, bars, dividend = self.build(special=True)
        computation = compute_adjustment_factors(bars, [dividend], as_of=AS_OF)
        assert computation.exact[(sid, D1)][1] == Fraction(19, 20)
        assert computation.provenance.special_dividends_applied == 1


def test_same_date_split_and_dividend_compose_split_first() -> None:
    """Prev close 100; 2-for-1 split AND dividend 1, both ex D2; close 49.
    Hand-derived: split first → post-split prev close 50; dividend factor = 1 - 1/50 =
    49/50; adjusted D1 = 100 x 1/2 x 49/50 = 49 → zero return across the event."""
    sid = new_security_id()
    bars = [bar(sid, D1, "100"), bar(sid, D2, "49")]
    actions = [
        Split(
            security_id=sid, ex_date=D2, source="t", available_at=AS_OF, new_shares=2, old_shares=1
        ),
        Dividend(
            security_id=sid,
            ex_date=D2,
            source="t",
            available_at=AS_OF,
            amount=Decimal("1"),
            currency="GBX",
        ),
    ]
    computation = compute_adjustment_factors(bars, actions, as_of=AS_OF)
    assert computation.exact[(sid, D1)] == (Fraction(1, 2), Fraction(49, 50))
    returns = total_returns(bars, computation)["total_return"].to_list()
    assert returns == [Decimal("0")]


def test_missing_previous_close_is_an_error_not_a_reach_back() -> None:
    sid = new_security_id()
    dividend = Dividend(
        security_id=sid,
        ex_date=D2,
        source="t",
        available_at=AS_OF,
        amount=Decimal("1"),
        currency="GBX",
    )
    with pytest.raises(AdjustmentError, match="no bar before ex-date"):
        compute_adjustment_factors(
            [bar(sid, D2, "50"), bar(sid, D3, "50")], [dividend], as_of=AS_OF
        )

    stale = [bar(sid, date(2020, 2, 1), "50"), bar(sid, D2, "50")]
    with pytest.raises(AdjustmentError, match="refusing to reach further back"):
        compute_adjustment_factors(stale, [dividend], as_of=AS_OF)


def test_rights_issue_flagged_never_silently_adjusted() -> None:
    sid = new_security_id()
    bars = [bar(sid, D1, "100"), bar(sid, D2, "95")]
    rights = RightsIssue(
        security_id=sid,
        ex_date=D2,
        source="t",
        available_at=AS_OF,
        new_shares=1,
        old_shares=4,
        subscription_price=Decimal("80"),
        currency="GBX",
    )
    computation = compute_adjustment_factors(bars, [rights], as_of=AS_OF)
    assert computation.exact[(sid, D1)] == (Fraction(1), Fraction(1))  # untouched…
    assert any("rights issue" in w for w in computation.provenance.warnings)  # …but loud


def test_provider_reconciliation_reports_discrepancies() -> None:
    sid = new_security_id()
    bars = [
        bar(sid, D1, "100", provider_adjusted_close=Decimal("50")),
        bar(sid, D2, "50", provider_adjusted_close=Decimal("50")),
    ]
    split = Split(
        security_id=sid, ex_date=D2, source="t", available_at=AS_OF, new_shares=2, old_shares=1
    )
    computation = compute_adjustment_factors(bars, [split], as_of=AS_OF)
    report = reconcile_provider_adjusted(bars, computation)
    assert report["relative_difference"].to_list() == [Decimal("0"), Decimal("0")]


def test_float_boundary_is_explicit_and_single(tmp_path: Path) -> None:
    sid = new_security_id()
    bars = [bar(sid, D1, "10"), bar(sid, D2, "50")]
    split = Split(
        security_id=sid, ex_date=D2, source="t", available_at=AS_OF, new_shares=1, old_shares=5
    )
    computation = compute_adjustment_factors(bars, [split], as_of=AS_OF)
    floats = factors_to_float_frame(computation)
    assert floats["split_factor"].dtype == pl.Float64

    target = tmp_path / "factors" / "run-1"
    write_adjustment_factors(computation, target)
    assert (target / "factors.parquet").exists()
    assert (target / "provenance.json").exists()
    with pytest.raises(AdjustmentError, match="never overwritten"):
        write_adjustment_factors(computation, target)
