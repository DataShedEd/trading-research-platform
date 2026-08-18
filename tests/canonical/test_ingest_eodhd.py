from datetime import UTC, date, datetime
from decimal import Decimal

from trp.canonical.ingest_eodhd import bars_from_eodhd, dividends_from_eodhd, splits_from_eodhd
from trp.domain.identifiers import new_security_id

INGESTED = datetime(2026, 8, 18, 6, 0, tzinfo=UTC)

EOD = (
    b'[{"date": "2018-01-12", "open": 14.5, "high": 14.6, "low": 14.1, "close": 14.27,'
    b' "adjusted_close": 14.27, "volume": 39638017},'
    b' {"date": "bad-date", "open": 1, "high": 1, "low": 1, "close": 1, "volume": 0},'
    b' {"date": "2018-01-11", "open": 17.5, "high": 18.0, "low": 14.0, "close": 14.5,'
    b' "adjusted_close": 14.5, "volume": 21000000}]'
)
SPLITS = (
    b'[{"date": "2021-02-15", "split": "15.000000/19.000000"},'
    b' {"date": "2020-01-01", "split": "garbage"}]'
)
DIVS = (
    b'[{"date": "2021-02-15", "recordDate": "2021-02-16", "paymentDate": "2021-02-26",'
    b' "value": 0.5093, "currency": "GBP", "period": "Special"},'
    b' {"date": "2019-05-01", "value": 0.02}]'
)


def test_bars_decimal_fidelity_and_reject_reporting() -> None:
    sid = new_security_id()
    bars, rejects = bars_from_eodhd(EOD, sid, currency="GBX", ingested_at=INGESTED)
    assert len(bars) == 2
    assert len(rejects) == 1 and "bad-date" in rejects[0]
    carillion_last = next(b for b in bars if b.trade_date == date(2018, 1, 12))
    assert carillion_last.close == Decimal("14.27")  # exact, no float round trip
    assert str(carillion_last.close) == "14.27"
    assert carillion_last.currency == "GBX"  # pence, as quoted
    assert carillion_last.provider_adjusted_close == Decimal("14.27")


def test_splits_exact_ratio_and_dec007_imputation() -> None:
    sid = new_security_id()
    splits, rejects = splits_from_eodhd(SPLITS, sid)
    (tesco_consolidation,) = splits
    assert (tesco_consolidation.new_shares, tesco_consolidation.old_shares) == (15, 19)
    assert tesco_consolidation.available_at_imputed  # DEC-007: no announcement timestamp
    assert tesco_consolidation.available_at == datetime(2021, 2, 15, tzinfo=UTC)
    assert len(rejects) == 1 and "garbage" in rejects[0]


def test_dividends_keep_currency_verbatim_and_reject_missing_currency() -> None:
    sid = new_security_id()
    dividends, rejects = dividends_from_eodhd(DIVS, sid)
    (special,) = dividends
    # EODHD reports LSE dividends in POUNDS while quoting prices in pence: preserved.
    assert special.amount == Decimal("0.5093")
    assert special.currency == "GBP"
    assert special.pay_date == date(2021, 2, 26)
    assert len(rejects) == 1 and "2019-05-01" in rejects[0]  # no currency -> reject, loudly


def test_non_json_payload_is_a_reject_not_a_crash() -> None:
    bars, rejects = bars_from_eodhd(
        b"<html>guru meditation</html>", new_security_id(), currency="GBX", ingested_at=INGESTED
    )
    assert bars == [] and len(rejects) == 1
