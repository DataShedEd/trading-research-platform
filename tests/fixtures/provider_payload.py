"""A checked-in synthetic provider payload for the QNT-021 normalisation suite.

Not a recording of any real feed — real payload shapes arrive with the adapters in
QNT-031…033. This one is built to exercise every branch the mapper has: items that map
cleanly, an item reported with the opposite sign to the canonical convention, an item the
mapping deliberately refuses, and an item nobody has mapped at all. The last two are the
interesting ones, because both must survive normalisation with their raw names intact.
"""

from decimal import Decimal
from pathlib import Path

from trp.canonical.fundamentals.normalisation import ProviderLineItem
from trp.domain.fundamentals import StatementType

STUB_PROVIDER = "stub"

MAPPINGS_DIRECTORY = Path(__file__).parent / "mappings"


def stub_payload() -> list[ProviderLineItem]:
    """FY2019 for one company, as the fixture provider would state it.

    Deliberately in an order that is neither alphabetical nor grouped by statement, so a
    test asserting deterministic output is actually asserting something.
    """
    return [
        ProviderLineItem(
            statement=StatementType.CASH_FLOW,
            name="capitalExpenditure",
            value=Decimal("480000000"),  # positive magnitude: the mapping flips it
        ),
        ProviderLineItem(
            statement=StatementType.INCOME, name="turnover", value=Decimal("6420000000")
        ),
        ProviderLineItem(
            statement=StatementType.BALANCE, name="sharesInIssue", value=Decimal("1850000000")
        ),
        ProviderLineItem(
            statement=StatementType.INCOME, name="costOfSales", value=Decimal("4100000000")
        ),
        ProviderLineItem(
            statement=StatementType.CASH_FLOW,
            name="profitForTheYear",  # same provider name as the income line: excluded here
            value=Decimal("512000000"),
        ),
        ProviderLineItem(
            statement=StatementType.INCOME, name="profitForTheYear", value=Decimal("512000000")
        ),
        ProviderLineItem(
            statement=StatementType.INCOME,
            name="adjustedEbitdaMargin",  # nobody has mapped this: it must come back unmapped
            value=Decimal("0.184"),
        ),
        ProviderLineItem(
            statement=StatementType.BALANCE, name="totalAssets", value=Decimal("9310000000")
        ),
        ProviderLineItem(
            statement=StatementType.CASH_FLOW,
            name="netCashFromOperations",
            value=Decimal("1130000000"),
        ),
    ]
