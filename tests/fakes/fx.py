"""A fixed-table FxRateProvider for tests. Never a production implementation.

Real FX history arrives with provider data (QNT-017 defines the interface only), so suites
needing a cross-currency conversion script the rates they mean:

    fx = FixedRateFx({("GBP", "USD"): Decimal("1.25")})
    convert_with_fx(Money(amount=Decimal("4521.5"), unit="GBX"), "USD", on=d, provider=fx)

Two deliberate refusals, both mirroring what a real implementation must do:

* an unscripted pair or a pair only scripted in the opposite direction raises
  ``FxRateUnavailableError`` — it is never inverted by division (an inverse is a rounding
  step, and a silently inverted rate is exactly the error class the direction convention
  exists to prevent);
* the requested date is recorded in ``calls`` rather than ignored, so a suite can assert
  its code asked for the rate as of the date it meant.
"""

from collections.abc import Mapping
from datetime import date
from decimal import Decimal

from trp.domain.reference import FxRateUnavailableError


class FixedRateFx:
    """Serves scripted ``(base, quote) -> rate`` pairs, constant across dates.

    Rates follow the ``FxRateProvider`` convention: units of ``quote`` per unit of ``base``.
    """

    def __init__(self, rates: Mapping[tuple[str, str], Decimal] | None = None) -> None:
        self._rates = dict(rates or {})
        self.calls: list[tuple[str, str, date]] = []

    def rate(self, base: str, quote: str, on: date) -> Decimal:
        self.calls.append((base, quote, on))
        if base == quote:
            return Decimal(1)
        try:
            return self._rates[(base, quote)]
        except KeyError:
            raise FxRateUnavailableError(base, quote, on) from None
