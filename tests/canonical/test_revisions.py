from datetime import UTC, datetime
from decimal import Decimal

import pytest

from tests.fixtures.fundamentals import fundamental, tesco_restatement
from trp.canonical.fundamentals.revisions import (
    CurrencyChangeError,
    RevisionOrderError,
    classify_observations,
)
from trp.domain.fundamentals import FundamentalValue
from trp.domain.security import revalidated_copy


def as_observation(record: FundamentalValue) -> FundamentalValue:
    """Strip revision bookkeeping: providers serve plain observations."""
    return revalidated_copy(record, revision_sequence=0, revised_at=None)


def test_new_fact_gets_sequence_zero() -> None:
    original, _ = tesco_restatement()
    result = classify_observations([], [as_observation(original)])
    assert result.new_facts == 1
    (stored,) = result.to_append
    assert stored.revision_sequence == 0
    assert stored.revised_at is None


def test_identical_reobservation_is_idempotent_no_op() -> None:
    original, _ = tesco_restatement()
    first_pass = classify_observations([], [as_observation(original)])
    second_pass = classify_observations(list(first_pass.to_append), [as_observation(original)])
    assert second_pass.to_append == ()
    assert second_pass.unchanged == 1


def test_scale_variants_are_the_same_fact() -> None:
    record = fundamental(value=Decimal("100"))
    rescaled = revalidated_copy(record, value=Decimal("100.00"))
    result = classify_observations([record], [rescaled])
    assert result.to_append == ()
    assert result.unchanged == 1


def test_changed_value_becomes_a_revision_preserving_the_original() -> None:
    original, restated = tesco_restatement(security_id=None)
    existing = list(classify_observations([], [as_observation(original)]).to_append)
    snapshot = [r.model_dump() for r in existing]

    incoming = revalidated_copy(restated, revision_sequence=0, revised_at=None)
    result = classify_observations(existing, [incoming])
    assert result.revisions == 1
    (revision,) = result.to_append
    assert revision.revision_sequence == 1
    assert revision.revised_at == restated.available_at
    assert revision.available_at == restated.available_at  # never inherited from the original
    # The original rows are untouched — append-only, structurally.
    assert [r.model_dump() for r in existing[:1]] == snapshot[:1]


def test_restatement_availability_must_strictly_increase() -> None:
    original, restated = tesco_restatement()
    existing = list(classify_observations([], [as_observation(original)]).to_append)
    stale = revalidated_copy(
        restated,
        revision_sequence=0,
        revised_at=None,
        available_at=original.available_at,  # same instant: rejected
        filed_at=original.available_at,
    )
    with pytest.raises(RevisionOrderError, match="strictly after"):
        classify_observations(existing, [stale])


def test_currency_change_is_a_data_error_not_a_revision() -> None:
    record = fundamental(currency="GBP")
    existing = list(classify_observations([], [record]).to_append)
    switched = revalidated_copy(
        record,
        currency="USD",
        value=Decimal("999"),
        available_at=datetime(2020, 6, 1, tzinfo=UTC),
    )
    with pytest.raises(CurrencyChangeError):
        classify_observations(existing, [switched])


def test_batch_classification_across_keys() -> None:
    revenue = fundamental(line_item="revenue")
    profit = revalidated_copy(revenue, line_item="operating_profit", value=Decimal("5"))
    result = classify_observations([], [revenue, profit])
    assert result.new_facts == 2
    assert {r.line_item for r in result.to_append} == {"revenue", "operating_profit"}
