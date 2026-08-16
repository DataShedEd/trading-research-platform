"""Canonical corporate-action records — where price history goes wrong if you let it.

Conventions, chosen to make direction and units impossible to mistake:

- **Ratios are exact integer pairs**, never decimals: a split/consolidation is
  ``new_shares`` per ``old_shares`` — a 2-for-1 split is (new=2, old=1); a 1-for-10
  consolidation is (new=1, old=10). ``ratio`` exposes the exact ``Fraction``; cumulative
  products in the adjustment engine stay exact.
- **Every monetary amount carries its currency and quotation unit** (GBX = pence).
- **``ex_date`` is the adjustment date** — the first date the price trades without the
  entitlement (or, for delistings/mergers/ticker changes, the first date the event
  applies). Record and pay dates are retained for reconciliation only.
- **``available_at``** (knowledge time, UTC) makes adjustments point-in-time queryable.
  Where a source provides none, it is imputed conservatively per DEC-007 as the start of
  the ex-date in UTC — the latest defensible moment, since the market applies the
  adjustment from the ex-date open — and flagged ``available_at_imputed``.
"""

from datetime import UTC, date, datetime, time
from decimal import Decimal
from fractions import Fraction
from typing import Annotated, Any, Literal, Self

from pydantic import Field, TypeAdapter, model_validator

from trp.domain.identifiers import SecurityId
from trp.domain.security import DelistingReason, FrozenModel

_CURRENCY = r"^[A-Z]{3}$"


def conservative_available_at(ex_date: date) -> datetime:
    """DEC-007 imputation for corporate actions: start of the ex-date, UTC."""
    return datetime.combine(ex_date, time.min, tzinfo=UTC)


class CorporateActionBase(FrozenModel):
    security_id: SecurityId
    ex_date: date
    record_date: date | None = None
    pay_date: date | None = None
    source: str = Field(min_length=1)
    available_at: datetime
    available_at_imputed: bool = False

    @model_validator(mode="before")
    @classmethod
    def _impute_availability(cls, data: Any) -> Any:
        if isinstance(data, dict) and data.get("available_at") is None:
            ex = data.get("ex_date")
            if isinstance(ex, str):
                ex = date.fromisoformat(ex)
            if isinstance(ex, date):
                data = {
                    **data,
                    "available_at": conservative_available_at(ex),
                    "available_at_imputed": True,
                }
        return data

    @model_validator(mode="after")
    def _dates_consistent(self) -> Self:
        if self.available_at.tzinfo is None:
            raise ValueError("available_at must be timezone-aware (UTC)")
        for label, value in (("record_date", self.record_date), ("pay_date", self.pay_date)):
            if value is not None and value < self.ex_date:
                raise ValueError(f"{label} ({value}) must be on or after ex_date ({self.ex_date})")
        return self


class Split(CorporateActionBase):
    """Split or consolidation: ``new_shares`` per ``old_shares``, exact."""

    action_type: Literal["split"] = "split"
    new_shares: int = Field(gt=0)
    old_shares: int = Field(gt=0)

    @property
    def ratio(self) -> Fraction:
        return Fraction(self.new_shares, self.old_shares)


class Dividend(CorporateActionBase):
    action_type: Literal["dividend"] = "dividend"
    amount: Decimal = Field(gt=0, description="per share, in `currency` quotation units")
    currency: str = Field(pattern=_CURRENCY, description="ISO 4217 or GBX for pence")
    special: bool = False


class RightsIssue(CorporateActionBase):
    """``new_shares`` offered per ``old_shares`` held at ``subscription_price``."""

    action_type: Literal["rights_issue"] = "rights_issue"
    new_shares: int = Field(gt=0)
    old_shares: int = Field(gt=0)
    subscription_price: Decimal = Field(gt=0)
    currency: str = Field(pattern=_CURRENCY)

    @property
    def ratio(self) -> Fraction:
        return Fraction(self.new_shares, self.old_shares)


class Merger(CorporateActionBase):
    """Consideration: cash per share, a share exchange ratio, or both."""

    action_type: Literal["merger"] = "merger"
    cash_amount: Decimal | None = Field(default=None, gt=0)
    cash_currency: str | None = Field(default=None, pattern=_CURRENCY)
    shares_new: int | None = Field(default=None, gt=0, description="acquirer shares received…")
    shares_old: int | None = Field(default=None, gt=0, description="…per target shares held")
    acquirer_security_id: SecurityId | None = None

    @model_validator(mode="after")
    def _consideration_present(self) -> Self:
        has_cash = self.cash_amount is not None
        has_shares = self.shares_new is not None
        if not has_cash and not has_shares:
            raise ValueError("merger requires cash consideration, share consideration, or both")
        if has_cash and self.cash_currency is None:
            raise ValueError("cash consideration requires a currency")
        if (self.shares_new is None) != (self.shares_old is None):
            raise ValueError("share consideration requires both shares_new and shares_old")
        return self

    @property
    def share_ratio(self) -> Fraction | None:
        if self.shares_new is None or self.shares_old is None:
            return None
        return Fraction(self.shares_new, self.shares_old)


class DelistingAction(CorporateActionBase):
    """Market-data record of a delisting; the security master lifecycle event (QNT-010)
    consumes these rather than duplicating them."""

    action_type: Literal["delisting"] = "delisting"
    reason: DelistingReason
    last_trading_date: date | None = None

    @model_validator(mode="after")
    def _last_trade_precedes_effect(self) -> Self:
        if self.last_trading_date is not None and self.last_trading_date >= self.ex_date:
            raise ValueError(
                f"last_trading_date ({self.last_trading_date}) must precede "
                f"ex_date ({self.ex_date}) — ex_date is the first date delisted"
            )
        return self


class TickerChangeAction(CorporateActionBase):
    action_type: Literal["ticker_change"] = "ticker_change"
    old_ticker: str = Field(min_length=1)
    new_ticker: str = Field(min_length=1)
    mic: str = Field(pattern=r"^[A-Z0-9]{4}$")


CorporateAction = Annotated[
    Split | Dividend | RightsIssue | Merger | DelistingAction | TickerChangeAction,
    Field(discriminator="action_type"),
]

corporate_action_adapter: TypeAdapter[CorporateAction] = TypeAdapter(CorporateAction)
