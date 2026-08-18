"""The portfolio ledger (QNT-051): positions, cash, and an append-only event log.

Backtest accounting errors are silent and directional, so this ledger is deliberately
noisy: every change is an event, the accounting identity (value = cash + sum of quantity times
mark) is recomputable from the log alone, and a position can only leave the book through
an explicit sale, delisting proceeds, or a written-off failure — never by omission.

Conventions (documented, tested):
- Quantities are whole shares (purchases floor to whole shares); everything is in the
  exchange quote unit (GBX for XLON) as exact ``Decimal``.
- Marks use RAW as-traded prices; corporate actions are applied as ledger events (an
  adjusted-price mark would double-count them).
- Dividends credit on the EX-DATE for the quantity held at that morning's open. Real cash
  arrives at the pay date; the simplification is documented and slightly favourable on
  reinvestment timing (weeks at most), accepted until pay-date data quality justifies
  the extra machinery.
- Splits multiply quantity by new/old; a fractional remainder is paid as cash in lieu at
  the ex-date mark, so position value is unchanged across the event.
- A delisting resolves to proceeds where terms are known, or a write-off to zero for a
  failure. Where terms are genuinely unknown the conservative default is the write-off,
  and the event says so (QUANT_PRINCIPLES §5).
"""

from datetime import date
from decimal import Decimal
from enum import StrEnum
from fractions import Fraction

from pydantic import Field

from trp.domain.identifiers import SecurityId
from trp.domain.security import FrozenModel


class EventKind(StrEnum):
    DEPOSIT = "deposit"
    BUY = "buy"
    SELL = "sell"
    DIVIDEND = "dividend"
    SPLIT = "split"
    CASH_IN_LIEU = "cash_in_lieu"
    DELISTING_PROCEEDS = "delisting_proceeds"
    DELISTING_WRITEOFF = "delisting_writeoff"


class LedgerEvent(FrozenModel):
    on: date
    kind: EventKind
    security_id: SecurityId | None = None
    quantity_delta: int = 0
    cash_delta: Decimal = Decimal(0)
    price: Decimal | None = None
    costs: Decimal = Field(default=Decimal(0), ge=0, description="explicit, reconcilable")
    note: str = Field(default="", max_length=300)


class LedgerError(Exception):
    pass


class Portfolio:
    def __init__(self, initial_cash: Decimal, start: date) -> None:
        self._cash = Decimal(0)
        self._positions: dict[SecurityId, int] = {}
        self._events: list[LedgerEvent] = []
        self._record(
            LedgerEvent(
                on=start, kind=EventKind.DEPOSIT, cash_delta=initial_cash, note="initial cash"
            )
        )

    # ------------------------------------------------------------------ inspection
    @property
    def cash(self) -> Decimal:
        return self._cash

    def quantity(self, security_id: SecurityId) -> int:
        return self._positions.get(security_id, 0)

    def positions(self) -> dict[SecurityId, int]:
        return dict(self._positions)

    def events(self) -> tuple[LedgerEvent, ...]:
        return tuple(self._events)

    def value(self, marks: dict[SecurityId, Decimal]) -> Decimal:
        total = self._cash
        for security_id, quantity in self._positions.items():
            mark = marks.get(security_id)
            if mark is None:
                raise LedgerError(f"no mark for held position {security_id}")
            total += mark * quantity
        return total

    # ------------------------------------------------------------------- mutation
    def _record(self, event: LedgerEvent) -> None:
        if event.quantity_delta:
            assert event.security_id is not None
            new_quantity = self._positions.get(event.security_id, 0) + event.quantity_delta
            if new_quantity < 0:
                raise LedgerError(f"{event.security_id}: cannot go short ({new_quantity})")
            if new_quantity == 0:
                self._positions.pop(event.security_id, None)
            else:
                self._positions[event.security_id] = new_quantity
        self._cash += event.cash_delta
        if self._cash < 0:
            raise LedgerError(f"cash below zero after {event.kind} on {event.on}")
        self._events.append(event)

    def buy(
        self, security_id: SecurityId, shares: int, price: Decimal, costs: Decimal, on: date
    ) -> None:
        if shares <= 0:
            raise LedgerError("buy requires a positive share count")
        self._record(
            LedgerEvent(
                on=on,
                kind=EventKind.BUY,
                security_id=security_id,
                quantity_delta=shares,
                cash_delta=-(price * shares + costs),
                price=price,
                costs=costs,
            )
        )

    def sell(
        self, security_id: SecurityId, shares: int, price: Decimal, costs: Decimal, on: date
    ) -> None:
        if shares <= 0:
            raise LedgerError("sell requires a positive share count")
        self._record(
            LedgerEvent(
                on=on,
                kind=EventKind.SELL,
                security_id=security_id,
                quantity_delta=-shares,
                cash_delta=price * shares - costs,
                price=price,
                costs=costs,
            )
        )

    def credit_dividend(
        self, security_id: SecurityId, per_share: Decimal, on: date, *, special: bool
    ) -> None:
        held = self.quantity(security_id)
        if held <= 0:
            return
        self._record(
            LedgerEvent(
                on=on,
                kind=EventKind.DIVIDEND,
                security_id=security_id,
                cash_delta=per_share * held,
                price=per_share,
                note="special" if special else "ordinary",
            )
        )

    def apply_split(
        self, security_id: SecurityId, new_shares: int, old_shares: int, mark: Decimal, on: date
    ) -> None:
        held = self.quantity(security_id)
        if held <= 0:
            return
        exact = Fraction(held * new_shares, old_shares)
        whole = int(exact)  # floor
        remainder = exact - whole
        self._record(
            LedgerEvent(
                on=on,
                kind=EventKind.SPLIT,
                security_id=security_id,
                quantity_delta=whole - held,
                note=f"{new_shares}:{old_shares} on {held} shares",
            )
        )
        if remainder:
            # Cash in lieu at the post-split mark keeps value unchanged across the event.
            in_lieu = mark * Decimal(remainder.numerator) / Decimal(remainder.denominator)
            self._record(
                LedgerEvent(
                    on=on,
                    kind=EventKind.CASH_IN_LIEU,
                    security_id=security_id,
                    cash_delta=in_lieu,
                    price=mark,
                    note=f"fractional {remainder}",
                )
            )

    def resolve_delisting(
        self, security_id: SecurityId, proceeds_per_share: Decimal | None, on: date, note: str
    ) -> None:
        held = self.quantity(security_id)
        if held <= 0:
            return
        if proceeds_per_share is None:
            self._record(
                LedgerEvent(
                    on=on,
                    kind=EventKind.DELISTING_WRITEOFF,
                    security_id=security_id,
                    quantity_delta=-held,
                    note=f"terms unknown, conservative write-off: {note}"[:300],
                )
            )
        else:
            self._record(
                LedgerEvent(
                    on=on,
                    kind=EventKind.DELISTING_PROCEEDS,
                    security_id=security_id,
                    quantity_delta=-held,
                    cash_delta=proceeds_per_share * held,
                    price=proceeds_per_share,
                    note=note[:300],
                )
            )


def replay(events: tuple[LedgerEvent, ...]) -> tuple[Decimal, dict[SecurityId, int]]:
    """Reconstruct (cash, positions) from the log alone — the accounting identity's
    independent witness, used by tests and the daily engine assertion."""
    cash = Decimal(0)
    positions: dict[SecurityId, int] = {}
    for event in events:
        cash += event.cash_delta
        if event.quantity_delta and event.security_id is not None:
            positions[event.security_id] = (
                positions.get(event.security_id, 0) + event.quantity_delta
            )
            if positions[event.security_id] == 0:
                del positions[event.security_id]
    return cash, positions
