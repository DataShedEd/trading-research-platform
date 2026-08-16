from datetime import UTC, date, datetime
from decimal import Decimal
from fractions import Fraction

import pytest
from pydantic import ValidationError

from trp.domain.corporate_actions import (
    DelistingAction,
    Dividend,
    Merger,
    RightsIssue,
    Split,
    TickerChangeAction,
    conservative_available_at,
    corporate_action_adapter,
)
from trp.domain.identifiers import new_security_id
from trp.domain.security import DelistingReason

KNOWN = datetime(2020, 2, 14, 8, 0, tzinfo=UTC)


def common(**overrides: object) -> dict[str, object]:
    fields: dict[str, object] = {
        "security_id": new_security_id(),
        "ex_date": date(2020, 3, 2),
        "source": "test",
        "available_at": KNOWN,
    }
    fields.update(overrides)
    return fields


class TestSplit:
    def test_two_for_one(self) -> None:
        split = Split(**common(), new_shares=2, old_shares=1)  # type: ignore[arg-type]
        assert split.ratio == Fraction(2, 1)

    def test_one_for_three_consolidation_stays_exact(self) -> None:
        consolidation = Split(**common(), new_shares=1, old_shares=3)  # type: ignore[arg-type]
        assert consolidation.ratio == Fraction(1, 3)
        assert consolidation.ratio != Decimal("0.3333333333")
        # Round trip through serialisation preserves the integer pair exactly.
        again = Split.model_validate(consolidation.model_dump())
        assert again.ratio == Fraction(1, 3)


class TestDividend:
    def test_ordinary_dividend(self) -> None:
        dividend = Dividend(**common(), amount=Decimal("32.2"), currency="GBX")  # type: ignore[arg-type]
        assert not dividend.special
        assert dividend.amount == Decimal("32.2")

    def test_special_dividend_distinguished(self) -> None:
        special = Dividend(**common(), amount=Decimal("60"), currency="GBX", special=True)  # type: ignore[arg-type]
        assert special.special

    def test_currency_is_mandatory(self) -> None:
        with pytest.raises(ValidationError):
            Dividend(**common(), amount=Decimal("32.2"))  # type: ignore[arg-type,call-arg]


class TestRightsIssue:
    def test_one_for_four_at_subscription_price(self) -> None:
        rights = RightsIssue(
            **common(),  # type: ignore[arg-type]
            new_shares=1,
            old_shares=4,
            subscription_price=Decimal("185"),
            currency="GBX",
        )
        assert rights.ratio == Fraction(1, 4)
        assert rights.subscription_price == Decimal("185")


class TestMerger:
    def test_cash_and_shares_consideration(self) -> None:
        acquirer = new_security_id()
        merger = Merger(
            **common(),  # type: ignore[arg-type]
            cash_amount=Decimal("1.08"),
            cash_currency="GBP",
            shares_new=3,
            shares_old=11,
            acquirer_security_id=acquirer,
        )
        assert merger.share_ratio == Fraction(3, 11)
        assert merger.acquirer_security_id == acquirer

    def test_consideration_required(self) -> None:
        with pytest.raises(ValidationError, match="cash consideration, share consideration"):
            Merger(**common())  # type: ignore[arg-type]

    def test_cash_without_currency_rejected(self) -> None:
        with pytest.raises(ValidationError, match="requires a currency"):
            Merger(**common(), cash_amount=Decimal("1.08"))  # type: ignore[arg-type]


class TestDelistingAndTickerChange:
    def test_delisting_terms(self) -> None:
        delisting = DelistingAction(
            **common(),  # type: ignore[arg-type]
            reason=DelistingReason.FAILURE,
            last_trading_date=date(2020, 2, 28),
        )
        assert delisting.reason is DelistingReason.FAILURE

    def test_last_trading_date_must_precede_effect(self) -> None:
        with pytest.raises(ValidationError, match="must precede"):
            DelistingAction(
                **common(),  # type: ignore[arg-type]
                reason=DelistingReason.FAILURE,
                last_trading_date=date(2020, 3, 2),
            )

    def test_ticker_change_terms(self) -> None:
        change = TickerChangeAction(**common(), old_ticker="RDSB", new_ticker="SHEL", mic="XLON")  # type: ignore[arg-type]
        assert (change.old_ticker, change.new_ticker) == ("RDSB", "SHEL")


class TestCommonBehaviour:
    def test_discriminated_union_rejects_unknown_type(self) -> None:
        with pytest.raises(ValidationError):
            corporate_action_adapter.validate_python({**common(), "action_type": "spinoff"})

    def test_discriminated_union_dispatches_by_type(self) -> None:
        parsed = corporate_action_adapter.validate_python(
            {**common(), "action_type": "split", "new_shares": 2, "old_shares": 1}
        )
        assert isinstance(parsed, Split)

    def test_record_and_pay_dates_must_follow_ex_date(self) -> None:
        with pytest.raises(ValidationError, match="pay_date"):
            Dividend(
                **common(),  # type: ignore[arg-type]
                amount=Decimal("10"),
                currency="GBP",
                pay_date=date(2020, 2, 1),
            )

    def test_missing_available_at_imputed_conservatively(self) -> None:
        dividend = Dividend(
            **common(available_at=None),  # type: ignore[arg-type]
            amount=Decimal("10"),
            currency="GBP",
        )
        assert dividend.available_at_imputed
        assert dividend.available_at == conservative_available_at(date(2020, 3, 2))
        assert dividend.available_at.tzinfo is not None
        # Conservative direction: never earlier than any real announcement could matter —
        # the adjustment is knowable no later than the ex-date itself.
        assert dividend.available_at == datetime(2020, 3, 2, 0, 0, tzinfo=UTC)

    def test_explicit_available_at_is_not_flagged(self) -> None:
        dividend = Dividend(**common(), amount=Decimal("10"), currency="GBP")  # type: ignore[arg-type]
        assert not dividend.available_at_imputed
