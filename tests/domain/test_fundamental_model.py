from datetime import UTC, date, datetime, timedelta
from decimal import Decimal

import pytest
from pydantic import ValidationError

from tests.fixtures.fundamentals import FILED, PERIOD_END, fundamental, revision_series
from trp.domain.fundamentals import (
    RevisionSeriesError,
    check_revision_series,
    conservative_available_at,
)


class TestRecordInvariants:
    def test_valid_record_constructs(self) -> None:
        record = fundamental()
        assert record.value == Decimal("1250000000")
        assert record.revision_sequence == 0

    def test_record_is_immutable(self) -> None:
        record = fundamental()
        with pytest.raises(ValidationError):
            record.value = Decimal("1")  # type: ignore[misc]

    def test_available_at_required_and_aware(self) -> None:
        with pytest.raises(ValidationError):
            fundamental(available_at=None)
        with pytest.raises(ValidationError, match="timezone-aware"):
            fundamental(available_at=datetime(2020, 3, 12, 7, 0))  # noqa: DTZ001 — the point

    def test_float_value_rejected_not_coerced(self) -> None:
        with pytest.raises(ValidationError):
            fundamental(value=1250000000.0)

    def test_currency_validated(self) -> None:
        with pytest.raises(ValidationError):
            fundamental(currency="gbp")

    def test_available_at_before_period_end_rejected(self) -> None:
        early = datetime(2019, 12, 30, 23, 59, tzinfo=UTC)
        with pytest.raises(ValidationError, match="precedes period_end"):
            fundamental(available_at=early, filed_at=early)

    def test_available_at_exactly_at_period_end_accepted(self) -> None:
        boundary = datetime.combine(PERIOD_END, datetime.min.time(), tzinfo=UTC)
        record = fundamental(available_at=boundary)
        assert record.available_at == boundary

    def test_revision_requires_revised_at_and_original_forbids_it(self) -> None:
        with pytest.raises(ValidationError, match="must carry revised_at"):
            fundamental(revision_sequence=1)
        with pytest.raises(ValidationError, match="must not carry revised_at"):
            fundamental(revision_sequence=0, revised_at=FILED)

    def test_imputation_flag_iff_rule(self) -> None:
        record = fundamental(
            availability_imputed=True,
            imputation_rule="uk-annual-lag-90d",
            available_at=conservative_available_at(PERIOD_END, timedelta(days=90)),
        )
        assert record.availability_imputed
        with pytest.raises(ValidationError, match="imputation_rule"):
            fundamental(availability_imputed=True)
        with pytest.raises(ValidationError, match="imputation_rule"):
            fundamental(imputation_rule="uk-annual-lag-90d")


def test_conservative_available_at_is_late_by_construction() -> None:
    imputed = conservative_available_at(date(2019, 12, 31), timedelta(days=90))
    assert imputed == datetime(2020, 3, 30, 0, 0, tzinfo=UTC)
    assert imputed > datetime.combine(date(2019, 12, 31), datetime.min.time(), tzinfo=UTC)


class TestRevisionSeries:
    def test_well_formed_series_passes(self) -> None:
        check_revision_series(revision_series())

    def test_empty_series_passes(self) -> None:
        check_revision_series([])

    def test_gap_in_sequence_fails(self) -> None:
        original, _, second = revision_series()
        with pytest.raises(RevisionSeriesError, match="contiguous"):
            check_revision_series([original, second])

    def test_duplicate_sequence_fails(self) -> None:
        original, first, _ = revision_series()
        duplicate = fundamental(
            security_id=original.security_id,
            value=Decimal("999"),
            available_at=first.available_at,
            revised_at=first.revised_at,
            revision_sequence=1,
        )
        with pytest.raises(RevisionSeriesError, match="contiguous"):
            check_revision_series([original, first, duplicate])

    def test_backwards_revised_at_fails(self) -> None:
        original, first, second = revision_series()
        swapped_first = fundamental(
            security_id=original.security_id,
            value=first.value,
            available_at=second.available_at,
            revised_at=second.revised_at,
            revision_sequence=1,
        )
        swapped_second = fundamental(
            security_id=original.security_id,
            value=second.value,
            available_at=first.available_at,
            revised_at=first.revised_at,
            revision_sequence=2,
        )
        with pytest.raises(RevisionSeriesError, match="strictly increase"):
            check_revision_series([original, swapped_first, swapped_second])

    def test_mixed_keys_fail(self) -> None:
        series = revision_series()
        stray = fundamental(line_item="operating_profit")
        with pytest.raises(RevisionSeriesError, match="distinct series keys"):
            check_revision_series([*series, stray])
