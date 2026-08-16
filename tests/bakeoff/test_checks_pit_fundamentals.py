"""QNT-035 checks against the four provider shapes the ticket names.

Fixtures: a provider with true first-known timestamps, one with filing dates only, one with
period ends only, and one whose restatements are invisible. Each must produce the expected
classification, and each placeholder pattern must be caught for what it is.
"""

import json
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from typing import Any

import pytest

from trp.bakeoff import checks as checks_module
from trp.bakeoff.checks import Criterion, Outcome
from trp.bakeoff.checks_pit_fundamentals import (
    DEC007_ASSUMED_LAG_DAYS,
    PIT_FUNDAMENTAL_CHECKS,
    AvailabilityClass,
    FilingLagDistributionCheck,
    FundamentalAvailabilityClassCheck,
    FundamentalTimestampPlausibilityCheck,
    FundamentalTimestampPresenceCheck,
    RestatementVisibilityCheck,
    derive_available_at,
    percentile,
    register_all,
)
from trp.bakeoff.payloads import DECISION_TRIGGER, MEASUREMENT_PREFIX, parse_statements
from trp.bakeoff.universe.loader import Market, UniverseEntry, load_universe
from trp.providers.base import Dataset

UNIVERSE = load_universe()
TODAY = date(2026, 8, 16)

TESCO_PERIOD = "2014-08-23"
TESCO_ITEM = "trading_profit_guidance"


def entry(key: str) -> UniverseEntry:
    return next(e for e in UNIVERSE.entries if e.key == key)


def statements_page(*statements: dict[str, Any]) -> bytes:
    return json.dumps({"statements": list(statements)}).encode()


def annual(period_end: str, **extra: Any) -> dict[str, Any]:
    return {"period_end": period_end, "period_type": "annual", "currency": "GBP", **extra}


def filing_only_pages(lags: tuple[int, ...] = (95, 88, 101, 76)) -> list[bytes]:
    """A provider with filing dates only — the field every candidate actually offers."""
    statements = [
        annual(
            (period_end := date(2018 + index, 12, 31)).isoformat(),
            filed_at=(period_end + timedelta(days=lag)).isoformat(),
            items={"revenue": "1000"},
        )
        for index, lag in enumerate(lags)
    ]
    return [statements_page(*statements)]


# ---------------------------------------------------------------- timestamp presence


def test_timestamps_present_on_every_statement_passes() -> None:
    (finding,) = FundamentalTimestampPresenceCheck(TODAY).run(entry("tesco"), filing_only_pages())
    assert finding.outcome is Outcome.PASS
    assert finding.observed is not None
    assert "4/4" in finding.observed
    assert "filed_at" in finding.observed  # the field inspected, recorded verbatim


def test_mostly_missing_timestamps_fail() -> None:
    pages = [
        statements_page(
            annual("2019-12-31", filed_at="2020-03-12"),
            annual("2020-12-31"),
            annual("2021-12-31"),
            annual("2022-12-31"),
        )
    ]
    (finding,) = FundamentalTimestampPresenceCheck(TODAY).run(entry("tesco"), pages)
    assert finding.outcome is Outcome.FAIL
    assert finding.observed is not None and "1/4" in finding.observed
    assert "imputed conservatively (DEC-007)" in finding.explanation


def test_the_field_name_is_reported_verbatim_not_normalised() -> None:
    pages = [statements_page(annual("2023-12-31", acceptedDate="2024-02-01 06:01:36"))]
    (finding,) = FundamentalTimestampPresenceCheck(TODAY).run(entry("apple"), pages)
    assert finding.observed is not None and "acceptedDate" in finding.observed


def test_empty_fundamentals_payload_fails_with_evidence() -> None:
    (finding,) = FundamentalTimestampPresenceCheck(TODAY).run(entry("tesco"), [b"{}"])
    assert finding.outcome is Outcome.FAIL
    assert finding.observed is not None and "statements" in finding.observed


# ------------------------------------------------------------- timestamp plausibility


def test_filing_date_equal_to_period_end_is_caught_as_a_default() -> None:
    pages = [
        statements_page(
            annual("2019-12-31", filed_at="2019-12-31"),
            annual("2020-12-31", filed_at="2020-12-31"),
            annual("2021-12-31", filed_at="2021-12-31"),
        )
    ]
    (finding,) = FundamentalTimestampPlausibilityCheck(TODAY).run(entry("tesco"), pages)
    assert finding.outcome is Outcome.FAIL
    assert "period end repeated" in finding.explanation


def test_identical_lag_on_every_record_is_caught_as_imputation() -> None:
    pages = filing_only_pages(lags=(90, 90, 90, 90))
    (finding,) = FundamentalTimestampPlausibilityCheck(TODAY).run(entry("tesco"), pages)
    assert finding.outcome is Outcome.FAIL
    assert "suspicious uniformity" in finding.explanation


def test_epoch_and_future_timestamps_are_caught() -> None:
    pages = [
        statements_page(
            annual("2019-12-31", filed_at="1970-01-01"),
            annual("2020-12-31", filed_at="2021-03-01"),
        )
    ]
    (finding,) = FundamentalTimestampPlausibilityCheck(TODAY).run(entry("tesco"), pages)
    assert finding.outcome is Outcome.FAIL
    assert "placeholders" in finding.explanation


def test_first_of_month_clustering_is_caught() -> None:
    pages = [
        statements_page(
            annual("2019-12-31", filed_at="2020-03-01"),
            annual("2020-12-31", filed_at="2021-04-01"),
            annual("2021-12-31", filed_at="2022-05-01"),
        )
    ]
    (finding,) = FundamentalTimestampPlausibilityCheck(TODAY).run(entry("tesco"), pages)
    assert finding.outcome is Outcome.FAIL
    assert "first of the month" in finding.explanation


def test_timestamps_that_vary_like_real_filings_pass() -> None:
    (finding,) = FundamentalTimestampPlausibilityCheck(TODAY).run(
        entry("tesco"), filing_only_pages()
    )
    assert finding.outcome is Outcome.PASS


def test_absent_timestamps_are_not_double_counted_as_implausible() -> None:
    pages = [statements_page(annual("2019-12-31"), annual("2020-12-31"))]
    (finding,) = FundamentalTimestampPlausibilityCheck(TODAY).run(entry("tesco"), pages)
    assert finding.outcome is Outcome.NOT_APPLICABLE
    assert "not counted twice" in finding.explanation


# ------------------------------------------------------------------- classification


def test_availability_classes_are_ordered_best_first() -> None:
    ranks = [c.rank for c in AvailabilityClass]
    assert ranks == sorted(ranks)
    assert AvailabilityClass.FIRST_KNOWN.rank < AvailabilityClass.FILING_ONLY.rank
    assert AvailabilityClass.FIRST_KNOWN.acceptable and AvailabilityClass.FILING_ONLY.acceptable
    assert not AvailabilityClass.PERIOD_END_ONLY.acceptable
    assert not AvailabilityClass.NOTHING_USABLE.acceptable


def test_first_known_timestamps_classify_as_first_known() -> None:
    pages = [statements_page(annual("2019-12-31", first_known_at="2020-03-12T07:00:00Z"))]
    (finding,) = FundamentalAvailabilityClassCheck(TODAY).run(entry("tesco"), pages)
    assert finding.outcome is Outcome.PASS
    assert finding.observed is not None
    assert AvailabilityClass.FIRST_KNOWN.value in finding.observed


def test_filing_dates_only_classify_as_filing_only_and_still_pass() -> None:
    (finding,) = FundamentalAvailabilityClassCheck(TODAY).run(entry("tesco"), filing_only_pages())
    assert finding.outcome is Outcome.PASS
    assert finding.observed is not None
    assert AvailabilityClass.FILING_ONLY.value in finding.observed
    assert "not when the market could act on it" in finding.explanation


def test_period_ends_only_classify_as_imputation_required_and_fail() -> None:
    pages = [statements_page(annual("2019-12-31"), annual("2020-12-31"))]
    (finding,) = FundamentalAvailabilityClassCheck(TODAY).run(entry("tesco"), pages)
    assert finding.outcome is Outcome.FAIL
    assert finding.observed is not None
    assert AvailabilityClass.PERIOD_END_ONLY.value in finding.observed
    assert "DEC-007 imputation" in finding.explanation


def test_nothing_usable_classifies_as_nothing_usable() -> None:
    pages = [statements_page({"items": {"revenue": "1000"}})]
    (finding,) = FundamentalAvailabilityClassCheck(TODAY).run(entry("tesco"), pages)
    assert finding.outcome is Outcome.FAIL
    assert finding.observed is not None
    assert AvailabilityClass.NOTHING_USABLE.value in finding.observed


# -------------------------------------------------------------------- restatements


def restatement_pages(
    *, original: bool, restated: bool, distinct_stamps: bool = True
) -> list[bytes]:
    statements: list[dict[str, Any]] = []
    if original:
        statements.append(
            {
                "period_end": TESCO_PERIOD,
                "period_type": "interim",
                "filed_at": "2014-08-29",
                "revision": 0,
                "items": {TESCO_ITEM: "1100000000"},
            }
        )
    if restated:
        statements.append(
            {
                "period_end": TESCO_PERIOD,
                "period_type": "interim",
                "filed_at": "2014-08-29" if not distinct_stamps else "2014-09-22",
                "revision": 1,
                "restated": True,
                "items": {TESCO_ITEM: "850000000"},
            }
        )
    return [statements_page(*statements)]


def test_both_revisions_visible_with_distinct_timestamps_passes() -> None:
    (finding,) = RestatementVisibilityCheck().run(
        entry("tesco"), restatement_pages(original=True, restated=True)
    )
    assert finding.outcome is Outcome.PASS
    assert "genuinely point-in-time" in finding.explanation


def test_only_the_restated_value_is_the_current_view_failure() -> None:
    (finding,) = RestatementVisibilityCheck().run(
        entry("tesco"), restatement_pages(original=False, restated=True)
    )
    assert finding.outcome is Outcome.FAIL
    assert "silently overwritten" in finding.explanation
    assert "knows the correction before it was announced" in finding.explanation


def test_only_the_original_value_fails_the_other_way() -> None:
    (finding,) = RestatementVisibilityCheck().run(
        entry("tesco"), restatement_pages(original=True, restated=False)
    )
    assert finding.outcome is Outcome.FAIL
    assert "never reached the provider" in finding.explanation


def test_revisions_without_distinct_timestamps_are_not_point_in_time() -> None:
    (finding,) = RestatementVisibilityCheck().run(
        entry("tesco"), restatement_pages(original=True, restated=True, distinct_stamps=False)
    )
    assert finding.outcome is Outcome.FAIL
    assert "cannot tell which was knowable when" in finding.explanation


def test_line_item_absent_for_the_period_fails_distinctly() -> None:
    pages = [statements_page({"period_end": TESCO_PERIOD, "items": {"revenue": "1000"}})]
    (finding,) = RestatementVisibilityCheck().run(entry("tesco"), pages)
    assert finding.outcome is Outcome.FAIL
    assert "not exposed for the affected period" in finding.explanation


def test_a_third_value_neither_original_nor_restated_fails() -> None:
    pages = [statements_page({"period_end": TESCO_PERIOD, "items": {TESCO_ITEM: "500000000"}})]
    (finding,) = RestatementVisibilityCheck().run(entry("tesco"), pages)
    assert finding.outcome is Outcome.FAIL
    assert "third figure" in finding.explanation


def test_restatement_check_is_not_applicable_without_the_fact() -> None:
    (finding,) = RestatementVisibilityCheck().run(entry("shell"), [statements_page()])
    assert finding.outcome is Outcome.NOT_APPLICABLE


# --------------------------------------------------------------------- filing lag


def lag_pages(lags: tuple[int, ...]) -> list[bytes]:
    statements = [
        annual(
            (period_end := date(2015 + index, 12, 31)).isoformat(),
            filed_at=(period_end + timedelta(days=lag)).isoformat(),
            items={"revenue": "1"},
        )
        for index, lag in enumerate(lags)
    ]
    return [statements_page(*statements)]


def test_filing_lag_is_a_measurement_not_a_judgement() -> None:
    (finding,) = FilingLagDistributionCheck(TODAY).run(entry("tesco"), lag_pages((30, 40, 50, 60)))
    assert finding.outcome is Outcome.NOT_APPLICABLE  # excluded from scoring by construction
    assert finding.explanation.startswith(MEASUREMENT_PREFIX)
    assert finding.observed is not None
    assert (
        "n=4" in finding.observed and "median=" in finding.observed and "p90=" in finding.observed
    )


def test_observed_lag_within_the_assumption_is_reported_as_conservative() -> None:
    (finding,) = FilingLagDistributionCheck(TODAY).run(entry("tesco"), lag_pages((30, 40, 50, 60)))
    assert "within DEC-007's assumed 90d" in finding.explanation


def test_observed_lag_beyond_the_assumption_is_flagged_as_a_superseding_trigger() -> None:
    (finding,) = FilingLagDistributionCheck(TODAY).run(
        entry("tesco"), lag_pages((100, 110, 120, 130))
    )
    assert "EXCEEDS DEC-007's assumed 90d" in finding.explanation
    assert DECISION_TRIGGER in finding.explanation  # the report quotes these in full
    assert "do not edit DEC-007 in place" in finding.explanation


def test_thin_samples_report_percentiles_but_claim_nothing() -> None:
    (finding,) = FilingLagDistributionCheck(TODAY).run(entry("tesco"), lag_pages((200, 210)))
    assert "below the 3-record floor" in finding.explanation


def test_lag_is_not_measurable_without_timestamps() -> None:
    pages = [statements_page(annual("2019-12-31"), annual("2020-12-31"))]
    (finding,) = FilingLagDistributionCheck(TODAY).run(entry("tesco"), pages)
    assert finding.outcome is Outcome.NOT_APPLICABLE
    assert "not measurable" in finding.explanation
    assert "stands untested" in finding.explanation


def test_the_us_assumption_is_shorter_than_the_uk_one() -> None:
    assert (
        DEC007_ASSUMED_LAG_DAYS[Market.US]["annual"] < DEC007_ASSUMED_LAG_DAYS[Market.UK]["annual"]
    )


def test_percentile_is_nearest_rank() -> None:
    values = [10, 20, 30, 40]
    assert percentile(values, Decimal("0.5")) == 20
    assert percentile(values, Decimal("0.75")) == 30
    assert percentile(values, Decimal("0.9")) == 40
    assert percentile([7], Decimal("0.9")) == 7


# ------------------------------------------------------------- derived availability


def test_derived_availability_uses_a_real_timestamp_unchanged() -> None:
    (row,) = parse_statements(
        [statements_page(annual("2019-12-31", filed_at="2020-03-12T07:00:00Z"))]
    ).items
    available_at, imputed, rule = derive_available_at(row, Market.UK)
    assert available_at == datetime(2020, 3, 12, 7, tzinfo=UTC)
    assert not imputed and rule is None


def test_derived_availability_imputes_late_and_names_the_rule() -> None:
    (row,) = parse_statements([statements_page(annual("2019-12-31"))]).items
    available_at, imputed, rule = derive_available_at(row, Market.UK)
    assert imputed and rule == "uk-annual-lag-90d"
    assert available_at == datetime(2019, 12, 31, tzinfo=UTC) + timedelta(days=90)


def test_derived_availability_declines_to_invent_one() -> None:
    (row,) = parse_statements([statements_page({"items": {"revenue": "1"}})]).items
    available_at, imputed, rule = derive_available_at(row, Market.UK)
    assert available_at is None and imputed and rule is None


# ------------------------------------------------------------------------ wiring


def test_checks_declare_their_datasets_criteria_and_properties() -> None:
    tesco, shell = entry("tesco"), entry("shell")
    presence = FundamentalTimestampPresenceCheck()
    assert presence.criterion is Criterion.PIT_FUNDAMENTALS
    assert presence.applies_to(shell, Dataset.FUNDAMENTALS)
    assert presence.applies_to(shell, Dataset.FINANCIAL_PERIODS)
    assert not presence.applies_to(shell, Dataset.PRICES)
    restatement = RestatementVisibilityCheck()
    assert restatement.criterion is Criterion.REVISION_HISTORY
    assert restatement.applies_to(tesco, Dataset.FUNDAMENTALS)
    assert not restatement.applies_to(shell, Dataset.FUNDAMENTALS)


@pytest.fixture
def clean_registry() -> object:
    checks_module.clear_registry()
    yield None
    checks_module.clear_registry()
    register_all()


def test_registration_is_idempotent(clean_registry: object) -> None:
    register_all()
    register_all()
    names = {c.name for c in checks_module.registered_checks()}
    assert names == {c.name for c in PIT_FUNDAMENTAL_CHECKS}
