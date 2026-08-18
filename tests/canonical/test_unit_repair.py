"""QNT-093: GBX/GBP unit repair — synthetic fixtures for every repair rule."""

from datetime import date, timedelta
from decimal import Decimal

import polars as pl
import pytest

from trp.canonical.unit_repair import (
    UnitRepairError,
    audit_splits,
    repair_dividends,
    repair_prices,
    repair_splits,
)

A, B = "SEC-aaaa", "SEC-bbbb"


def price_frame(rows: list[tuple[str, date, str]]) -> pl.DataFrame:
    return pl.DataFrame(
        {
            "security_id": [r[0] for r in rows],
            "trade_date": [r[1] for r in rows],
            "open": [Decimal(r[2]) for r in rows],
            "high": [Decimal(r[2]) for r in rows],
            "low": [Decimal(r[2]) for r in rows],
            "close": [Decimal(r[2]) for r in rows],
            "volume": [1000] * len(rows),
        }
    )


def days(start: date, values: list[str], sid: str) -> list[tuple[str, date, str]]:
    return [(sid, start + timedelta(days=i), v) for i, v in enumerate(values)]


def dividend_frame(rows: list[tuple[str, date, str, str]]) -> pl.DataFrame:
    return pl.DataFrame(
        {
            "security_id": [r[0] for r in rows],
            "ex_date": [r[1] for r in rows],
            "amount": [Decimal(r[2]) for r in rows],
            "currency": [r[3] for r in rows],
        }
    )


NO_DIVIDENDS = dividend_frame([(A, date(2020, 1, 1), "0.10", "USD")]).clear()


def test_clean_gbx_series_is_untouched() -> None:
    frame = price_frame(days(date(2021, 1, 4), ["450", "452", "449", "455"], A))
    repaired, report = repair_prices(frame, NO_DIVIDENDS)
    assert repaired["close"].to_list() == frame["close"].to_list()
    assert not report.changed()
    assert not report.unresolved


def test_intra_series_flip_is_made_continuous() -> None:
    # 450p, then two days printed in pounds, then back to pence.
    frame = price_frame(days(date(2021, 1, 4), ["450", "4.52", "4.49", "455"], A))
    repaired, report = repair_prices(frame, NO_DIVIDENDS)
    assert [float(c) for c in repaired["close"]] == [450.0, 452.0, 449.0, 455.0]
    (change,) = report.changed()
    assert len(change.flips) == 2
    assert change.global_scale == 1


def test_whole_gbp_series_is_rescaled_by_level() -> None:
    frame = price_frame(days(date(2021, 1, 4), ["12.28", "12.31", "12.10"], A))
    repaired, report = repair_prices(frame, NO_DIVIDENDS)
    assert [float(c) for c in repaired["close"]] == [1228.0, 1231.0, 1210.0]
    (change,) = report.changed()
    assert change.global_scale == 100


def test_dividend_evidence_beats_the_level_heuristic() -> None:
    # Median close 32 could be 32p or £32; a 30p dividend on it says pounds (IHG's case).
    frame = price_frame(days(date(2021, 1, 4), ["32", "33", "31", "32"], A))
    dividends = dividend_frame(
        [
            (A, date(2021, 1, 5), "0.30", "GBP"),
            (A, date(2020, 1, 5), "0.30", "GBP"),
        ]
    )
    with_bars_2020 = pl.concat([price_frame(days(date(2020, 1, 6), ["30", "31"], A)), frame])
    _repaired, report = repair_prices(with_bars_2020, dividends)
    (change,) = report.changed()
    assert change.global_scale == 100


def test_gbx_series_with_gbx_labelled_dividends_is_not_rescaled() -> None:
    # BAE's case: 460p closes, dividends stated in pence and labelled GBX.
    frame = pl.concat(
        [
            price_frame(days(date(2020, 1, 6), ["455", "458"], A)),
            price_frame(days(date(2021, 1, 4), ["460", "462"], A)),
        ]
    )
    dividends = dividend_frame(
        [
            (A, date(2020, 1, 7), "13.2", "GBX"),
            (A, date(2021, 1, 5), "13.6", "GBX"),
        ]
    )
    _repaired, report = repair_prices(frame, dividends)
    assert not report.changed()


def test_scale_leaving_the_lattice_is_unresolved() -> None:
    # Two flips the same way = 10000x from the leading unit: nonsense, refuse to guess.
    frame = price_frame(days(date(2021, 1, 4), ["4500", "45", "0.45", "0.44"], A))
    repaired, report = repair_prices(frame, NO_DIVIDENDS)
    assert report.unresolved == [A]
    assert repaired["close"].to_list() == frame["close"].to_list()  # left untouched


def test_genuine_crash_is_not_a_flip() -> None:
    frame = price_frame(days(date(2021, 1, 4), ["400", "12", "10"], A))  # -97%: a collapse
    _repaired, report = repair_prices(frame, NO_DIVIDENDS)
    assert not next(s for s in report.securities if s.security_id == A).flips


def test_dividend_relabel_needs_pence_scale_and_high_yield() -> None:
    prices = price_frame(days(date(2021, 1, 4), ["500", "500", "500", "500"], A))
    dividends = dividend_frame(
        [
            (A, date(2021, 1, 5), "36.10", "GBP"),  # £36 'dividend' on 500p: pence-stated
            (A, date(2021, 1, 6), "0.12", "GBP"),  # normal 12p final
            (A, date(2021, 1, 7), "1.60", "GBP"),  # genuine 160p special (32%): kept
        ]
    )
    out, report = repair_dividends(dividends, prices)
    assert out["currency"].to_list() == ["GBX", "GBP", "GBP"]
    assert report.dividends_relabelled_gbx == 1
    assert len(report.dividends_high_yield_kept) == 1


def test_split_audit_verdicts() -> None:
    real = days(date(2021, 1, 4), ["900", "300", "301"], A)  # 3:1 split, price drops 3x
    pre_applied = days(date(2021, 1, 4), ["900", "898", "901"], B)  # no move at all
    prices = price_frame(real + pre_applied)
    splits = pl.DataFrame(
        {
            "security_id": [A, B],
            "ex_date": [date(2021, 1, 5), date(2021, 1, 5)],
            "new_shares": [3, 3],
            "old_shares": [1, 1],
        }
    )
    audit = audit_splits(splits, prices)
    assert audit["verdict"].to_list() == ["REAL", "PRE_APPLIED"]
    kept, _ = repair_splits(splits, prices)
    assert kept["security_id"].to_list() == [A]


def test_unadjudicated_unclear_split_raises() -> None:
    prices = price_frame(days(date(2021, 1, 4), ["900", "170", "171"], A))  # 5.3x move
    splits = pl.DataFrame(
        {
            "security_id": [A],
            "ex_date": [date(2021, 1, 5)],
            "new_shares": [3],
            "old_shares": [1],
        }
    )
    with pytest.raises(UnitRepairError, match="UNCLEAR"):
        repair_splits(splits, prices)
