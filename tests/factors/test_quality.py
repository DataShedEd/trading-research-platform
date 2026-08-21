"""QNT-045: quality factors against hand-computed synthetic statements."""

from datetime import UTC, date, datetime
from decimal import Decimal
from pathlib import Path

import pytest

from trp.canonical.fundamentals.storage import write_fundamentals
from trp.domain.fundamentals import FundamentalValue, PeriodType, StatementType
from trp.domain.identifiers import SecurityId, new_security_id
from trp.factors.compute import ComputeContext, compute_factor
from trp.factors.registry import FactorRegistry

REGISTRY = FactorRegistry.load()
T = date(2021, 6, 30)
AS_OF = datetime(2021, 7, 1, tzinfo=UTC)

STATEMENT_OF = {
    "revenue": StatementType.INCOME,
    "gross_profit": StatementType.INCOME,
    "operating_profit": StatementType.INCOME,
    "pre_tax_profit": StatementType.INCOME,
    "net_income": StatementType.INCOME,
    "ebit": StatementType.INCOME,
    "ebitda": StatementType.INCOME,
    "tax_expense": StatementType.INCOME,
    "total_assets": StatementType.BALANCE,
    "total_equity": StatementType.BALANCE,
    "net_debt": StatementType.BALANCE,
    "shares_outstanding": StatementType.BALANCE,
    "operating_cash_flow": StatementType.CASH_FLOW,
    "free_cash_flow": StatementType.CASH_FLOW,
    "dividends_paid": StatementType.CASH_FLOW,
    "share_buybacks": StatementType.CASH_FLOW,
}

# One coherent synthetic company, FY2020 (available 30 April 2021):
SNAPSHOT = {
    "revenue": "1000",
    "gross_profit": "300",
    "operating_profit": "150",
    "pre_tax_profit": "125",
    "net_income": "100",
    "ebit": "200",
    "ebitda": "250",
    "tax_expense": "25",
    "total_assets": "1000",
    "total_equity": "500",
    "net_debt": "200",
    "operating_cash_flow": "180",
    "free_cash_flow": "120",
}


def records(
    security_id: SecurityId,
    values: dict[str, str],
    period_end: date,
    available: datetime,
    *,
    currency: str = "GBP",
    revision: int = 0,
) -> list[FundamentalValue]:
    return [
        FundamentalValue(
            security_id=security_id,
            statement=STATEMENT_OF[item],
            line_item=item,
            period_end=period_end,
            period_type=PeriodType.ANNUAL,
            currency=currency,
            value=Decimal(value),
            available_at=available,
            revision_sequence=revision,
            revised_at=available if revision else None,
            source="fixture",
        )
        for item, value in values.items()
    ]


@pytest.fixture
def store(tmp_path: Path) -> Path:
    return tmp_path / "fundamentals"


def context_for(
    store: Path, *ids: SecurityId, end: date = T, as_of: datetime = AS_OF
) -> ComputeContext:
    return ComputeContext(security_ids=list(ids), end=end, as_of=as_of, fundamentals_root=store)


def value_of(name: str, context: ComputeContext) -> dict:  # type: ignore[type-arg]
    frame = compute_factor(REGISTRY.get(name), context)
    return frame.to_dicts()[0]


def seed(store: Path, sid: SecurityId, **overrides: str) -> None:
    values = {**SNAPSHOT, **overrides}
    write_fundamentals(
        records(sid, values, date(2020, 12, 31), datetime(2021, 4, 30, tzinfo=UTC)),
        store,
        source="fixture",
    )


HAND_VALUES = {
    "roe": 100 / 500,
    "gross_profitability": 300 / 1000,
    "operating_margin": 150 / 1000,
    "fcf_margin": 120 / 1000,
    "cash_conversion": (180 - 100) / 1000,
    "net_debt_to_equity": 200 / 500,
    "net_debt_to_ebitda": 200 / 250,
    # ROIC: tax rate 25/125 = 0.2 -> NOPAT 200 x 0.8 = 160; invested 500 + 200 = 700.
    "roic": 160 / 700,
}


@pytest.mark.parametrize("name, expected", sorted(HAND_VALUES.items()))
def test_hand_computed_snapshot_values(store: Path, name: str, expected: float) -> None:
    sid = new_security_id()
    seed(store, sid)
    row = value_of(name, context_for(store, sid))
    assert row["status"] == "ok"
    assert row["value"] == pytest.approx(expected)


def test_earnings_stability_hand_case(store: Path) -> None:
    sid = new_security_id()
    years = ((2016, "90"), (2017, "95"), (2018, "100"), (2019, "105"), (2020, "110"))
    for year, net_income in years:
        write_fundamentals(
            records(
                sid,
                {"net_income": net_income},
                date(year, 12, 31),
                datetime(year + 1, 4, 30, tzinfo=UTC),
            ),
            store,
            source="fixture",
        )
    row = value_of("earnings_stability", context_for(store, sid))
    # mean 100; sample stdev sqrt(250/4) = 7.9057; value = -stdev/|mean|.
    assert row["status"] == "ok"
    assert row["value"] == pytest.approx(-0.0790569, rel=1e-5)


def test_earnings_stability_needs_minimum_periods(store: Path) -> None:
    sid = new_security_id()
    for year in (2018, 2019, 2020):
        write_fundamentals(
            records(
                sid,
                {"net_income": "100"},
                date(year, 12, 31),
                datetime(year + 1, 4, 30, tzinfo=UTC),
            ),
            store,
            source="fixture",
        )
    row = value_of("earnings_stability", context_for(store, sid))
    assert row["status"] == "insufficient_data"


def test_negative_equity_is_not_meaningful_never_a_number(store: Path) -> None:
    sid = new_security_id()
    seed(store, sid, total_equity="-50")
    for name in ("roe", "net_debt_to_equity"):
        row = value_of(name, context_for(store, sid))
        assert row["status"] == "not_meaningful"
        assert row["value"] is None
        assert row["warnings"]


def test_negative_ebitda_refuses_the_debt_multiple(store: Path) -> None:
    sid = new_security_id()
    seed(store, sid, ebitda="-10")
    row = value_of("net_debt_to_ebitda", context_for(store, sid))
    assert row["status"] == "not_meaningful"


def test_missing_item_is_no_data(store: Path) -> None:
    """A security missing one required item is no_data — while a definition naming an
    item absent from the whole dataset still fails loudly (the typo guard upstream)."""
    sid, other = new_security_id(), new_security_id()
    seed(store, other)  # the item exists in the dataset, just not for `sid`
    values = {k: v for k, v in SNAPSHOT.items() if k != "gross_profit"}
    write_fundamentals(
        records(sid, values, date(2020, 12, 31), datetime(2021, 4, 30, tzinfo=UTC)),
        store,
        source="fixture",
    )
    row = value_of("gross_profitability", context_for(store, sid))
    assert row["status"] == "no_data"


def test_value_before_availability_uses_the_prior_report(store: Path) -> None:
    """The QNT-045 acceptance case: at a date after FY2020's period end but before its
    availability, the FY2019 figures are the truth of the moment."""
    sid = new_security_id()
    write_fundamentals(
        records(
            sid,
            {**SNAPSHOT, "net_income": "80"},
            date(2019, 12, 31),
            datetime(2020, 4, 30, tzinfo=UTC),
        ),
        store,
        source="fixture",
    )
    seed(store, sid)  # FY2020: net_income 100, available 30 Apr 2021
    before = context_for(store, sid, end=date(2021, 3, 31), as_of=datetime(2021, 3, 31, tzinfo=UTC))
    assert value_of("roe", before)["value"] == pytest.approx(80 / 500)
    after = context_for(store, sid)
    assert value_of("roe", after)["value"] == pytest.approx(100 / 500)


def test_restatement_respected_between_filings(store: Path) -> None:
    sid = new_security_id()
    seed(store, sid)  # original: net_income 100, available 30 Apr 2021
    write_fundamentals(
        records(
            sid,
            {"net_income": "60"},
            date(2020, 12, 31),
            datetime(2021, 9, 30, tzinfo=UTC),
            revision=1,
        ),
        store,
        source="fixture",
    )
    between = context_for(store, sid)  # as_of July 2021: original knowledge only
    assert value_of("roe", between)["value"] == pytest.approx(100 / 500)
    after = context_for(
        store, sid, end=date(2021, 12, 31), as_of=datetime(2021, 12, 31, tzinfo=UTC)
    )
    assert value_of("roe", after)["value"] == pytest.approx(60 / 500)
