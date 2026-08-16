"""Raw, as-traded daily bars.

These are the values that actually printed on the exchange, in the exchange's own
quotation unit (GBX for LSE ordinaries). Nothing in the platform ever modifies them:
adjusted prices and total returns are *derived* data produced by the adjustment engine
(QNT-015) from corporate-action records — see docs/QUANT_PRINCIPLES.md §3.

Volume is a whole number of shares. Providers reporting fractional or scaled volume are
rejected at the boundary (no rounding, no silent coercion) and surface in the QNT-019
validation report instead.
"""

from datetime import date, datetime
from decimal import Decimal
from typing import Self

from pydantic import Field, model_validator

from trp.domain.identifiers import SecurityId
from trp.domain.security import FrozenModel


class DailyBar(FrozenModel):
    security_id: SecurityId
    trade_date: date
    open: Decimal = Field(gt=0)
    high: Decimal = Field(gt=0)
    low: Decimal = Field(gt=0)
    close: Decimal = Field(gt=0)
    volume: int = Field(ge=0)
    currency: str = Field(
        pattern=r"^[A-Z]{3}$", description="quotation unit as traded; GBX = pence"
    )
    source: str = Field(min_length=1)
    ingested_at: datetime
    provider_adjusted_close: Decimal | None = Field(
        default=None,
        gt=0,
        description="the provider's own adjusted close, retained purely as a cross-check "
        "for our adjustment factors — never an input to returns",
    )

    @model_validator(mode="after")
    def _bar_is_possible(self) -> Self:
        checks = (
            ("high >= low", self.high >= self.low),
            ("high >= open", self.high >= self.open),
            ("high >= close", self.high >= self.close),
            ("low <= open", self.low <= self.open),
            ("low <= close", self.low <= self.close),
        )
        for invariant, ok in checks:
            if not ok:
                raise ValueError(
                    f"impossible bar for {self.security_id} on {self.trade_date}: "
                    f"violates {invariant} (o={self.open} h={self.high} "
                    f"l={self.low} c={self.close})"
                )
        if self.ingested_at.tzinfo is None:
            raise ValueError("ingested_at must be timezone-aware (UTC)")
        return self
