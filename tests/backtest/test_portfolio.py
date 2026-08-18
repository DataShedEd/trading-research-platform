"""QNT-051: hand-computed ledger cases — every number below is worked out on paper first."""

from datetime import date
from decimal import Decimal

import pytest

from trp.backtest.portfolio import EventKind, LedgerError, Portfolio, replay
from trp.domain.identifiers import SecurityId

START = date(2020, 1, 6)
SID = SecurityId("11111111-1111-1111-1111-111111111111")
OTHER = SecurityId("22222222-2222-2222-2222-222222222222")


def make_portfolio(cash: str = "100000") -> Portfolio:
    return Portfolio(Decimal(cash), START)


def test_initial_deposit() -> None:
    portfolio = make_portfolio()
    assert portfolio.cash == Decimal("100000")
    assert portfolio.positions() == {}
    assert portfolio.events()[0].kind is EventKind.DEPOSIT


def test_buy_and_sell_with_costs() -> None:
    portfolio = make_portfolio()
    portfolio.buy(SID, 10, Decimal("500"), Decimal("25"), START)
    # 100000 - 10*500 - 25
    assert portfolio.cash == Decimal("94975")
    assert portfolio.quantity(SID) == 10
    portfolio.sell(SID, 4, Decimal("520"), Decimal("10"), date(2020, 2, 3))
    # 94975 + 4*520 - 10
    assert portfolio.cash == Decimal("97045")
    assert portfolio.quantity(SID) == 6


def test_no_shorts_and_no_negative_cash() -> None:
    portfolio = make_portfolio("1000")
    with pytest.raises(LedgerError, match="short"):
        portfolio.sell(SID, 1, Decimal("500"), Decimal(0), START)
    with pytest.raises(LedgerError, match="cash below zero"):
        portfolio.buy(SID, 3, Decimal("500"), Decimal(0), START)


def test_zero_share_orders_rejected() -> None:
    portfolio = make_portfolio()
    with pytest.raises(LedgerError):
        portfolio.buy(SID, 0, Decimal("500"), Decimal(0), START)
    with pytest.raises(LedgerError):
        portfolio.sell(SID, -1, Decimal("500"), Decimal(0), START)


def test_ordinary_and_special_dividends_credit_held_quantity() -> None:
    portfolio = make_portfolio()
    portfolio.buy(SID, 100, Decimal("500"), Decimal(0), START)
    portfolio.credit_dividend(SID, Decimal("12.5"), date(2020, 3, 2), special=False)
    portfolio.credit_dividend(SID, Decimal("40"), date(2020, 3, 2), special=True)
    # 100000 - 50000 + 1250 + 4000
    assert portfolio.cash == Decimal("55250")
    kinds = [e for e in portfolio.events() if e.kind is EventKind.DIVIDEND]
    assert [e.note for e in kinds] == ["ordinary", "special"]


def test_dividend_on_unheld_security_records_nothing() -> None:
    portfolio = make_portfolio()
    portfolio.credit_dividend(OTHER, Decimal("10"), START, special=False)
    assert len(portfolio.events()) == 1  # just the deposit


def test_split_with_cash_in_lieu_preserves_value() -> None:
    portfolio = make_portfolio()
    portfolio.buy(SID, 5, Decimal("300"), Decimal(0), START)
    # 3:2 split on 5 shares = 7.5 -> 7 whole shares + 0.5 share cash in lieu.
    post_split_mark = Decimal("200")  # 300 * 2/3
    portfolio.apply_split(SID, 3, 2, post_split_mark, date(2020, 4, 1))
    assert portfolio.quantity(SID) == 7
    in_lieu = [e for e in portfolio.events() if e.kind is EventKind.CASH_IN_LIEU]
    assert len(in_lieu) == 1
    assert in_lieu[0].cash_delta == Decimal("100")  # 0.5 * 200
    # Value across the event is unchanged: 5*300 = 7*200 + 100.
    assert portfolio.value({SID: post_split_mark}) == Decimal("100000")


def test_consolidation() -> None:
    portfolio = make_portfolio()
    portfolio.buy(SID, 10, Decimal("50"), Decimal(0), START)
    # 1:4 consolidation on 10 shares = 2.5 -> 2 shares + 0.5 at the 200 mark.
    portfolio.apply_split(SID, 1, 4, Decimal("200"), date(2020, 4, 1))
    assert portfolio.quantity(SID) == 2
    assert portfolio.value({SID: Decimal("200")}) == Decimal("100000")


def test_exact_split_has_no_cash_in_lieu() -> None:
    portfolio = make_portfolio()
    portfolio.buy(SID, 4, Decimal("300"), Decimal(0), START)
    portfolio.apply_split(SID, 3, 2, Decimal("200"), date(2020, 4, 1))
    assert portfolio.quantity(SID) == 6
    assert not [e for e in portfolio.events() if e.kind is EventKind.CASH_IN_LIEU]


def test_delisting_with_proceeds_and_as_writeoff() -> None:
    portfolio = make_portfolio()
    portfolio.buy(SID, 10, Decimal("500"), Decimal(0), START)
    portfolio.buy(OTHER, 10, Decimal("100"), Decimal(0), START)
    portfolio.resolve_delisting(SID, Decimal("550"), date(2020, 6, 1), note="cash takeover")
    portfolio.resolve_delisting(OTHER, None, date(2020, 6, 1), note="administration")
    assert portfolio.positions() == {}
    # 100000 - 5000 - 1000 + 5500; OTHER written off to zero.
    assert portfolio.cash == Decimal("99500")
    kinds = {e.kind for e in portfolio.events()}
    assert EventKind.DELISTING_PROCEEDS in kinds
    assert EventKind.DELISTING_WRITEOFF in kinds


def test_value_requires_marks_for_all_held_positions() -> None:
    portfolio = make_portfolio()
    portfolio.buy(SID, 1, Decimal("500"), Decimal(0), START)
    with pytest.raises(LedgerError, match="no mark"):
        portfolio.value({})


def test_replay_reconstructs_state_from_the_log_alone() -> None:
    portfolio = make_portfolio()
    portfolio.buy(SID, 100, Decimal("500"), Decimal("25"), START)
    portfolio.credit_dividend(SID, Decimal("12.5"), date(2020, 3, 2), special=False)
    portfolio.apply_split(SID, 3, 2, Decimal("333"), date(2020, 4, 1))
    portfolio.sell(SID, 50, Decimal("340"), Decimal("10"), date(2020, 5, 1))
    portfolio.buy(OTHER, 7, Decimal("100"), Decimal(0), date(2020, 5, 1))
    portfolio.resolve_delisting(OTHER, None, date(2020, 6, 1), note="failure")
    cash, positions = replay(portfolio.events())
    assert cash == portfolio.cash
    assert positions == portfolio.positions()
