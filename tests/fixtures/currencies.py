"""A mixed-currency universe for the QNT-023 suite, plus the reference data it needs.

Three reporters, chosen because between them they break every implicit assumption a
factor might make about currency:

* **Shell-like** — UK-listed, quoted in pence, reporting in US dollars. Reporting currency
  and quotation currency differ, so a sterling research base means converting the
  fundamental and the price on different paths.
* **a GBP reporter** — reports in pounds but states earnings per share in pence, which is
  ordinary UK practice and the pence/pounds interaction in its natural habitat.
* **a EUR reporter** — and, from FY2020, a USD reporter. A company changing reporting
  currency between periods is not a revision (QNT-022's key excludes currency); each
  period simply keeps the currency it was filed in.

The figures are round synthetic numbers, not filed accounts: this fixture exists to test
conversion arithmetic, and inventing precise-looking financials would imply a provenance
it does not have. The FX rates are likewise synthetic but internally consistent (USD/GBP
and GBP/USD are exact inverses) so that a round trip in a test means something.

``markets.json`` (QNT-017) does not yet define EUR, so :func:`reference_with_eur` adds it
here rather than editing another ticket's reference file. Ingesting a euro reporter for
real needs that entry added to the packaged file.
"""

from dataclasses import dataclass
from datetime import UTC, date, datetime
from decimal import Decimal

from tests.fakes.fx import FixedRateFx
from trp.domain.fundamentals import FundamentalValue, PeriodType, StatementType
from trp.domain.identifiers import SecurityId, new_security_id
from trp.domain.reference import Currency, ReferenceData, default_reference_data

FY2019 = date(2019, 12, 31)
FY2020 = date(2020, 12, 31)
FY2019_AVAILABLE = datetime(2020, 3, 12, 7, 0, tzinfo=UTC)
FY2020_AVAILABLE = datetime(2021, 3, 11, 7, 0, tzinfo=UTC)

USD_GBP = Decimal("0.8")
GBP_USD = Decimal("1.25")
EUR_GBP = Decimal("0.85")
EUR_USD = EUR_GBP * GBP_USD  # 1.0625 — consistent with the pair above, exactly


def reference_with_eur() -> ReferenceData:
    """The packaged reference data plus a EUR entry, for the euro reporter."""
    euro = Currency(code="EUR", name="Euro", minor_unit=2)
    packaged = default_reference_data()
    return ReferenceData(
        schema_version=packaged.schema_version,
        notes="test-only: packaged reference data plus EUR",
        currencies=(*packaged.currencies, euro),
        exchanges=packaged.exchanges,
    )


def mixed_currency_fx() -> FixedRateFx:
    """Scripted rates for the pairs this fixture needs, constant across dates."""
    return FixedRateFx(
        {
            ("USD", "GBP"): USD_GBP,
            ("GBP", "USD"): GBP_USD,
            ("EUR", "GBP"): EUR_GBP,
            ("EUR", "USD"): EUR_USD,
        }
    )


@dataclass(frozen=True)
class MixedCurrencyUniverse:
    """Three securities and their fundamentals, with the identifiers tests need."""

    shell: SecurityId
    gbp_reporter: SecurityId
    eur_reporter: SecurityId
    records: tuple[FundamentalValue, ...]

    @property
    def security_ids(self) -> list[str]:
        return [self.shell, self.gbp_reporter, self.eur_reporter]


def _annual(
    security_id: SecurityId,
    statement: StatementType,
    line_item: str,
    currency: str,
    value: Decimal,
    *,
    period_end: date = FY2019,
    available_at: datetime = FY2019_AVAILABLE,
    source: str = "fixture:mixed-currency",
) -> FundamentalValue:
    return FundamentalValue(
        security_id=security_id,
        statement=statement,
        line_item=line_item,
        period_end=period_end,
        period_type=PeriodType.ANNUAL,
        currency=currency,
        value=value,
        available_at=available_at,
        source=source,
    )


def mixed_currency_universe() -> MixedCurrencyUniverse:
    """FY2019 for all three reporters, plus the euro reporter's FY2020 switch to USD."""
    shell = new_security_id()
    gbp_reporter = new_security_id()
    eur_reporter = new_security_id()

    records = (
        # UK-listed, quoted in pence, reports in dollars.
        _annual(shell, StatementType.INCOME, "revenue", "USD", Decimal("300000000000")),
        _annual(shell, StatementType.BALANCE, "total_equity", "USD", Decimal("180000000000")),
        _annual(
            shell,
            StatementType.CASH_FLOW,
            "capital_expenditure",
            "USD",
            Decimal("-22000000000"),
        ),
        # Reports in pounds; states EPS in pence, as UK companies do.
        _annual(gbp_reporter, StatementType.INCOME, "revenue", "GBP", Decimal("60000000000")),
        _annual(gbp_reporter, StatementType.BALANCE, "total_equity", "GBP", Decimal("12000000000")),
        _annual(gbp_reporter, StatementType.INCOME, "eps_basic", "GBX", Decimal("42.5")),
        _annual(
            gbp_reporter,
            StatementType.BALANCE,
            "shares_outstanding",
            "GBP",
            Decimal("2000000000"),
        ),
        # Euro reporter for FY2019 …
        _annual(eur_reporter, StatementType.INCOME, "revenue", "EUR", Decimal("90000000000")),
        _annual(eur_reporter, StatementType.BALANCE, "total_equity", "EUR", Decimal("30000000000")),
        # … and the same company reporting in dollars from FY2020.
        _annual(
            eur_reporter,
            StatementType.INCOME,
            "revenue",
            "USD",
            Decimal("105000000000"),
            period_end=FY2020,
            available_at=FY2020_AVAILABLE,
        ),
    )
    return MixedCurrencyUniverse(
        shell=shell, gbp_reporter=gbp_reporter, eur_reporter=eur_reporter, records=records
    )
