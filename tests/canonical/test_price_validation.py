"""Hand-built fixtures, one firing and one non-firing case per check.

The hard case is the last pair: a 2-for-1-split-shaped drop *with* the split recorded must
produce nothing, and the identical drop *without* it must be reported as a possible
unrecorded corporate action. That is the split inversion QNT-015's risk section is about —
without the action, every return over the window has the wrong sign and magnitude.
"""

from datetime import UTC, date, datetime
from decimal import Decimal

import polars as pl
import pytest

from tests.fixtures.prices import SEC_A, SEC_B, bar, series
from trp.canonical.calendars import get_trading_calendar
from trp.canonical.price_validation import (
    CHECK_NAMES,
    DEFAULT_THRESHOLDS,
    Severity,
    ValidationThresholds,
    check_adjustment_warnings,
    check_calendar_gaps,
    check_extreme_moves,
    check_non_positive_prices,
    check_stale_prices,
    check_volume_outliers,
    check_zero_volume,
    validate_bars,
    validate_prices,
)
from trp.canonical.prices import PRICES_DAILY_SCHEMA, bars_to_frame
from trp.derived.adjustments import compute_adjustment_factors
from trp.domain.corporate_actions import Dividend, RightsIssue, Split
from trp.domain.identifiers import SecurityId
from trp.domain.prices import DailyBar
from trp.domain.security import Listing

AS_OF = datetime(2021, 1, 1, tzinfo=UTC)
XLON = get_trading_calendar("XLON")

# The trading week 2-6 March 2020: Monday to Friday, no holiday among them.
MON, TUE, WED, THU, FRI = XLON.sessions_between(date(2020, 3, 2), date(2020, 3, 6))


def listing(
    security_id: SecurityId = SEC_A,
    *,
    mic: str = "XLON",
    valid_from: date = date(2015, 1, 1),
    valid_to: date | None = None,
) -> Listing:
    return Listing(
        security_id=security_id,
        mic=mic,
        currency="GBX",
        valid_from=valid_from,
        valid_to=valid_to,
    )


def clean_bars(*, security_id: SecurityId = SEC_A, days: int = 20) -> list[DailyBar]:
    """A well-behaved series: every trading day present, prices and volume drifting."""
    sessions = XLON.sessions_between(date(2020, 2, 3), date(2020, 3, 31))[:days]
    return [
        bar(
            session,
            str(Decimal(100) + Decimal(index) / 4),
            security_id=security_id,
            volume=1000 + index * 17,
        )
        for index, session in enumerate(sessions)
    ]


class TestCleanData:
    def test_clean_fixture_produces_no_findings(self) -> None:
        report = validate_bars(clean_bars(), as_of=AS_OF, listings=[listing()])
        assert report.findings == ()
        assert report.bars_checked == 20
        assert report.securities_checked == 1

    def test_every_check_is_counted_even_at_zero(self) -> None:
        report = validate_bars(clean_bars(), as_of=AS_OF, listings=[listing()])
        assert set(report.counts) == set(CHECK_NAMES)
        assert set(report.counts.values()) == {0}

    def test_report_records_the_thresholds_it_applied(self) -> None:
        thresholds = ValidationThresholds(extreme_move=Decimal("0.10"))
        report = validate_bars(
            clean_bars(), as_of=AS_OF, listings=[listing()], thresholds=thresholds
        )
        assert report.thresholds.extreme_move == Decimal("0.10")
        assert report.thresholds is not DEFAULT_THRESHOLDS

    def test_no_check_modifies_its_input_frame(self) -> None:
        frame = bars_to_frame(
            [
                *clean_bars(),
                bar(date(2020, 4, 1), "10", volume=0),  # something for every check to find
            ]
        )
        before = frame.clone()
        validate_prices(frame, as_of=AS_OF, listings=[listing()])
        assert frame.equals(before)

    def test_as_of_must_be_timezone_aware(self) -> None:
        with pytest.raises(ValueError, match="timezone-aware"):
            validate_bars(clean_bars(), as_of=datetime(2021, 1, 1))  # noqa: DTZ001


class TestCalendarGaps:
    def test_a_missing_tuesday_is_reported_with_its_date(self) -> None:
        bars = series([MON, WED, THU, FRI], ["100", "101", "102", "103"])
        findings = check_calendar_gaps(bars_to_frame(bars), [listing()])
        assert len(findings) == 1
        gap = findings[0]
        assert gap.check == "calendar_gap"
        assert gap.severity is Severity.WARNING
        assert (gap.start_date, gap.end_date) == (TUE, TUE)
        assert gap.evidence_map["dates"] == TUE.isoformat()
        assert gap.evidence_map["mic"] == "XLON"

    def test_consecutive_missing_days_collapse_into_one_run(self) -> None:
        bars = series([MON, THU, FRI], ["100", "101", "102"])
        findings = check_calendar_gaps(bars_to_frame(bars), [listing()])
        assert len(findings) == 1
        assert (findings[0].start_date, findings[0].end_date) == (TUE, WED)
        assert findings[0].evidence_map["missing_days"] == "2"

    def test_a_holiday_is_not_a_gap(self) -> None:
        # Good Friday 2020-04-10 and Easter Monday 2020-04-13 are LSE holidays.
        sessions = XLON.sessions_between(date(2020, 4, 8), date(2020, 4, 15))
        bars = series(list(sessions), ["100"] * len(sessions))
        assert check_calendar_gaps(bars_to_frame(bars), [listing()]) == ()

    def test_a_weekend_is_not_a_gap(self) -> None:
        bars = series(
            [THU, FRI, *XLON.sessions_between(date(2020, 3, 9), date(2020, 3, 9))],
            ["100", "101", "102"],
        )
        assert check_calendar_gaps(bars_to_frame(bars), [listing()]) == ()

    def test_no_gaps_after_delisting(self) -> None:
        # The listing closes after Tuesday; Wednesday onward is not a gap, it is gone.
        bars = series([MON, TUE], ["100", "101"])
        listings = [listing(valid_to=WED)]
        assert check_calendar_gaps(bars_to_frame(bars), listings, end=FRI) == ()

    def test_days_before_the_listing_opened_are_not_gaps(self) -> None:
        bars = series([THU, FRI], ["100", "101"])
        listings = [listing(valid_from=THU)]
        assert check_calendar_gaps(bars_to_frame(bars), listings, start=MON) == ()

    def test_a_security_with_no_listing_is_reported_not_skipped_silently(self) -> None:
        findings = check_calendar_gaps(bars_to_frame(series([MON, WED], ["100", "101"])), [])
        assert [f.check for f in findings] == ["listing_unknown"]
        assert findings[0].severity is Severity.INFO

    def test_an_unsupported_mic_is_reported_rather_than_raising(self) -> None:
        findings = check_calendar_gaps(
            bars_to_frame(series([MON, WED], ["100", "101"])), [listing(mic="XSES")]
        )
        assert [f.check for f in findings] == ["calendar_unavailable"]

    def test_a_window_outside_the_calendar_range_is_narrowed_and_said_so(self) -> None:
        bars = series([date(1998, 6, 1), date(1998, 6, 3)], ["100", "101"])
        findings = check_calendar_gaps(bars_to_frame(bars), [listing(valid_from=date(1990, 1, 1))])
        assert [f.check for f in findings] == ["calendar_range_clamped"]


class TestExtremeMoves:
    """Prev close 100, next close 50 — a 2-for-1 split shape, with and without the split."""

    def bars(self) -> list[DailyBar]:
        return series([MON, TUE, WED], ["100", "100", "50"])

    def split(self, **overrides: object) -> Split:
        fields: dict[str, object] = {
            "security_id": SEC_A,
            "ex_date": WED,
            "new_shares": 2,
            "old_shares": 1,
            "source": "test",
            "available_at": datetime(2020, 2, 1, tzinfo=UTC),
        }
        fields.update(overrides)
        return Split(**fields)  # type: ignore[arg-type]

    def test_the_split_shaped_drop_with_the_split_recorded_produces_nothing(self) -> None:
        findings = check_extreme_moves(bars_to_frame(self.bars()), [self.split()], as_of=AS_OF)
        assert findings == ()

    def test_the_identical_drop_with_no_action_is_flagged_as_a_possible_split(self) -> None:
        findings = check_extreme_moves(bars_to_frame(self.bars()), [], as_of=AS_OF)
        assert len(findings) == 1
        finding = findings[0]
        assert finding.check == "extreme_move"
        assert finding.severity is Severity.ERROR
        assert "2-for-1 split" in finding.detail
        assert (finding.start_date, finding.end_date) == (TUE, WED)
        assert finding.evidence_map["previous_close"] == "100.000000"
        assert finding.evidence_map["close"] == "50.000000"
        assert finding.evidence_map["move"] == "-0.500000"
        assert finding.evidence_map["price_ratio"] == "1/2"
        assert finding.threshold == "|move| >= 0.5"

    def test_an_action_outside_the_window_does_not_explain_the_move(self) -> None:
        far_away = self.split(
            ex_date=date(2020, 2, 3), available_at=datetime(2020, 1, 1, tzinfo=UTC)
        )
        findings = check_extreme_moves(bars_to_frame(self.bars()), [far_away], as_of=AS_OF)
        assert len(findings) == 1

    def test_a_move_that_matches_no_simple_ratio_is_a_warning_not_an_error(self) -> None:
        bars = series([MON, TUE], ["100", "30"])
        findings = check_extreme_moves(bars_to_frame(bars), [], as_of=AS_OF)
        assert len(findings) == 1
        assert findings[0].severity is Severity.WARNING
        assert "no corporate action recorded" in findings[0].detail

    def test_a_dividend_near_the_date_is_evidence_but_does_not_suppress(self) -> None:
        dividend = Dividend(
            security_id=SEC_A,
            ex_date=TUE,
            amount=Decimal("2.5"),
            currency="GBX",
            source="test",
            available_at=datetime(2020, 2, 1, tzinfo=UTC),
        )
        bars = series([MON, TUE], ["100", "30"])
        findings = check_extreme_moves(bars_to_frame(bars), [dividend], as_of=AS_OF)
        assert len(findings) == 1
        assert findings[0].evidence_map["actions_within_window"] == f"dividend@{TUE}"

    def test_the_threshold_bound_is_inclusive_so_an_exact_halving_fires(self) -> None:
        # -50.0% exactly fires; -49.9% does not. The inclusive bound is deliberate: an
        # unrecorded 2-for-1 split lands precisely on the boundary.
        assert len(check_extreme_moves(bars_to_frame(self.bars()), [], as_of=AS_OF)) == 1
        just_inside = series([MON, TUE], ["100", "50.1"])
        assert check_extreme_moves(bars_to_frame(just_inside), [], as_of=AS_OF) == ()

    def test_a_move_inside_the_threshold_is_not_reported(self) -> None:
        bars = series([MON, TUE], ["100", "60"])  # -40%, under the 50% default
        assert check_extreme_moves(bars_to_frame(bars), [], as_of=AS_OF) == ()
        tighter = ValidationThresholds(extreme_move=Decimal("0.3"))
        assert (
            len(check_extreme_moves(bars_to_frame(bars), [], as_of=AS_OF, thresholds=tighter)) == 1
        )

    def test_two_providers_series_are_never_interleaved_into_a_fake_move(self) -> None:
        # Same days from two sources at very different quotation units (GBX vs GBP): a
        # naive shift over security alone would manufacture a 99% move between them.
        bars = [
            bar(MON, "100", source="provider-a"),
            bar(TUE, "101", source="provider-a"),
            bar(MON, "1.00", source="provider-b"),
            bar(TUE, "1.01", source="provider-b"),
        ]
        assert check_extreme_moves(bars_to_frame(bars), [], as_of=AS_OF) == ()

    def test_a_rights_issue_explains_the_move_and_the_report_still_flags_the_security(
        self,
    ) -> None:
        rights = RightsIssue(
            security_id=SEC_A,
            ex_date=WED,
            new_shares=1,
            old_shares=1,
            subscription_price=Decimal("10"),
            currency="GBX",
            source="test",
            available_at=datetime(2020, 2, 1, tzinfo=UTC),
        )
        bars = self.bars()
        assert check_extreme_moves(bars_to_frame(bars), [rights], as_of=AS_OF) == ()

        # …but DEC-009 means the adjusted series is knowingly wrong, so it must surface.
        computation = compute_adjustment_factors(bars, [rights], as_of=AS_OF)
        report = validate_bars(
            bars,
            as_of=AS_OF,
            actions=[rights],
            listings=[listing()],
            adjustment=computation,
        )
        warnings = report.by_check("adjustment_warning")
        assert len(warnings) == 1
        assert "rights issue" in warnings[0].detail
        assert "DEC-009" in warnings[0].detail
        assert warnings[0].security_id == SEC_A
        assert warnings[0].start_date == WED

    def test_no_adjustment_warnings_when_there_is_nothing_to_warn_about(self) -> None:
        bars = self.bars()
        computation = compute_adjustment_factors(bars, [self.split()], as_of=AS_OF)
        assert check_adjustment_warnings(computation) == ()


class TestStalePrices:
    def test_a_run_of_five_identical_closes_is_reported_with_its_volumes(self) -> None:
        sessions = XLON.sessions_between(date(2020, 3, 2), date(2020, 3, 6))
        bars = series(list(sessions), ["100"] * 5, volumes=[10, 20, 30, 40, 50])
        findings = check_stale_prices(bars_to_frame(bars))
        assert len(findings) == 1
        finding = findings[0]
        assert finding.check == "stale_price_run"
        assert finding.severity is Severity.WARNING
        assert (finding.start_date, finding.end_date) == (MON, FRI)
        assert finding.evidence_map["run_length"] == "5"
        assert finding.evidence_map["volumes"] == "10, 20, 30, 40, 50"
        assert finding.evidence_map["total_volume"] == "150"

    def test_a_close_repeated_once_does_not_fire(self) -> None:
        bars = series([MON, TUE, WED], ["100", "100", "101"])
        assert check_stale_prices(bars_to_frame(bars)) == ()

    def test_a_stale_run_with_no_volume_at_all_is_an_error(self) -> None:
        sessions = XLON.sessions_between(date(2020, 3, 2), date(2020, 3, 6))
        bars = series(list(sessions), ["100"] * 5, volumes=[0] * 5)
        findings = check_stale_prices(bars_to_frame(bars))
        assert findings[0].severity is Severity.ERROR
        assert "carrying the last print forward" in findings[0].detail

    def test_the_run_length_threshold_is_configuration(self) -> None:
        bars = series([MON, TUE, WED], ["100", "100", "100"])
        assert check_stale_prices(bars_to_frame(bars)) == ()
        loose = ValidationThresholds(stale_run_days=3)
        assert len(check_stale_prices(bars_to_frame(bars), thresholds=loose)) == 1

    def test_runs_do_not_span_two_securities_at_the_same_price(self) -> None:
        bars = [
            *series([MON, TUE, WED], ["100"] * 3, security_id=SEC_A),
            *series([MON, TUE, WED], ["100"] * 3, security_id=SEC_B),
        ]
        loose = ValidationThresholds(stale_run_days=4)
        assert check_stale_prices(bars_to_frame(bars), thresholds=loose) == ()


class TestVolume:
    def test_zero_volume_days_are_reported_as_a_run(self) -> None:
        bars = series([MON, TUE, WED, THU], ["100", "101", "102", "103"], volumes=[10, 0, 0, 10])
        findings = check_zero_volume(bars_to_frame(bars), [listing()])
        assert len(findings) == 1
        finding = findings[0]
        assert finding.check == "zero_volume"
        assert (finding.start_date, finding.end_date) == (TUE, WED)
        assert finding.evidence_map["zero_volume_days"] == "2"
        assert finding.evidence_map["dates"] == f"{TUE}, {WED}"
        assert finding.evidence_map["half_days_in_run"] == "none"

    def test_a_fully_traded_series_produces_no_zero_volume_findings(self) -> None:
        assert check_zero_volume(bars_to_frame(clean_bars()), [listing()]) == ()

    def test_a_zero_volume_half_day_is_still_reported_but_flagged(self) -> None:
        # 2020-12-24 is a half day on XLON.
        christmas_eve = date(2020, 12, 24)
        bars = series([date(2020, 12, 23), christmas_eve], ["100", "101"], volumes=[10, 0])
        findings = check_zero_volume(bars_to_frame(bars), [listing()])
        assert len(findings) == 1
        assert findings[0].evidence_map["half_days_in_run"] == christmas_eve.isoformat()

    def volume_spike_bars(self, spike_on: date) -> list[DailyBar]:
        sessions = XLON.sessions_between(date(2020, 12, 1), date(2020, 12, 24))
        return [
            bar(
                session,
                str(Decimal(100) + Decimal(index) / 8),
                volume=100_000 if session == spike_on else 1_000,
            )
            for index, session in enumerate(sessions)
        ]

    def test_volume_far_above_the_trailing_median_is_an_outlier(self) -> None:
        bars = self.volume_spike_bars(date(2020, 12, 23))
        findings = check_volume_outliers(bars_to_frame(bars), [listing()])
        assert len(findings) == 1
        finding = findings[0]
        assert finding.check == "volume_outlier"
        assert finding.start_date == date(2020, 12, 23)
        assert finding.evidence_map["volume"] == "100000"
        assert finding.evidence_map["trailing_median_volume"] == "1000"

    def test_the_same_spike_on_a_half_day_is_excluded(self) -> None:
        bars = self.volume_spike_bars(date(2020, 12, 24))
        assert check_volume_outliers(bars_to_frame(bars), [listing()]) == ()

    def test_a_steady_series_produces_no_outliers(self) -> None:
        sessions = XLON.sessions_between(date(2020, 12, 1), date(2020, 12, 24))
        bars = [
            bar(session, str(Decimal(100) + Decimal(i) / 8), volume=1_000 + i * 20)
            for i, session in enumerate(sessions)
        ]
        assert check_volume_outliers(bars_to_frame(bars), [listing()]) == ()

    def test_the_check_does_not_fire_before_it_has_enough_history(self) -> None:
        bars = series([MON, TUE, WED], ["100", "101", "102"], volumes=[1_000, 1_000, 500_000])
        assert check_volume_outliers(bars_to_frame(bars), [listing()]) == ()


class TestNonPositivePrices:
    def bad_frame(self, **overrides: object) -> pl.DataFrame:
        row: dict[str, object] = {
            "security_id": SEC_A,
            "trade_date": MON,
            "open": Decimal("100"),
            "high": Decimal("100"),
            "low": Decimal("100"),
            "close": Decimal("100"),
            "volume": 1000,
            "currency": "GBX",
            "source": "test",
            "ingested_at": datetime(2020, 12, 31, tzinfo=UTC),
            "provider_adjusted_close": None,
        }
        row.update(overrides)
        return pl.DataFrame([row], schema=PRICES_DAILY_SCHEMA)

    def test_a_zero_close_that_bypassed_the_domain_model_is_caught(self) -> None:
        findings = check_non_positive_prices(self.bad_frame(close=Decimal("0")))
        assert len(findings) == 1
        assert findings[0].severity is Severity.ERROR
        assert findings[0].evidence_map["close"] == "0.000000"

    def test_a_null_price_is_caught(self) -> None:
        findings = check_non_positive_prices(self.bad_frame(low=None))
        assert len(findings) == 1
        assert findings[0].evidence_map["low"] == "None"

    def test_a_valid_bar_is_not_reported(self) -> None:
        assert check_non_positive_prices(self.bad_frame()) == ()

    def test_zero_volume_is_not_a_non_positive_price(self) -> None:
        assert check_non_positive_prices(self.bad_frame(volume=0)) == ()


class TestReportRendering:
    def report_with_findings(self) -> object:
        bars = series([MON, TUE], ["100", "30"])
        return validate_bars(bars, as_of=AS_OF, listings=[listing()])

    def test_to_frame_has_a_fixed_schema_and_one_row_per_finding(self) -> None:
        bars = series([MON, TUE], ["100", "30"])
        report = validate_bars(bars, as_of=AS_OF, listings=[listing()])
        frame = report.to_frame()
        assert frame.height == len(report.findings) == 1
        assert frame.columns == [
            "check",
            "severity",
            "security_id",
            "start_date",
            "end_date",
            "detail",
            "threshold",
            "evidence",
        ]
        assert frame.get_column("check").to_list() == ["extreme_move"]
        assert '"close": "30.000000"' in frame.get_column("evidence").to_list()[0]

    def test_to_frame_of_a_clean_run_is_empty_but_typed(self) -> None:
        report = validate_bars(clean_bars(), as_of=AS_OF, listings=[listing()])
        frame = report.to_frame()
        assert frame.is_empty()
        assert frame.schema["start_date"] == pl.Date

    def test_markdown_summary_names_the_checks_and_the_findings(self) -> None:
        bars = series([MON, TUE], ["100", "30"])
        report = validate_bars(bars, as_of=AS_OF, listings=[listing()])
        rendered = report.to_markdown()
        assert "# Price validation report" in rendered
        assert "| extreme_move | 1 |" in rendered
        assert "| calendar_gap | 0 |" in rendered
        assert str(TUE) in rendered

    def test_markdown_of_a_clean_run_says_so(self) -> None:
        report = validate_bars(clean_bars(), as_of=AS_OF, listings=[listing()])
        assert "No findings." in report.to_markdown()

    def test_findings_can_be_filtered_by_severity(self) -> None:
        bars = series([MON, TUE, WED], ["100", "100", "50"])
        report = validate_bars(bars, as_of=AS_OF, listings=[listing()])
        assert len(report.by_severity(Severity.ERROR)) == 1
        assert report.by_severity(Severity.INFO) == ()
