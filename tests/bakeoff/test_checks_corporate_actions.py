"""QNT-034 checks against synthetic payloads: a correct provider and five broken ones.

Every check is exercised in both directions — a check that has never been seen to fail is
not evidence of anything. Payloads follow the neutral convention documented in
`trp.bakeoff.payloads`; no provider, no network.
"""

import json
from datetime import date, timedelta
from decimal import Decimal
from typing import Any

import pytest

from trp.bakeoff import checks as checks_module
from trp.bakeoff.checks import Outcome
from trp.bakeoff.checks_corporate_actions import (
    CORPORATE_ACTION_CHECKS,
    DelistedPriceHistoryCheck,
    DividendAmountAndExDateCheck,
    PriceHistoryDepthCheck,
    RawVersusAdjustedCheck,
    SplitRatioAndExDateCheck,
    TickerChangeContinuityCheck,
    register_all,
    unit_conversion,
)
from trp.bakeoff.payloads import EXPECTATION_REVIEW_PREFIX
from trp.bakeoff.universe.loader import (
    AwkwardProperty,
    Identifier,
    Market,
    UniverseEntry,
    load_universe,
)
from trp.providers.base import Dataset

UNIVERSE = load_universe()


def entry(key: str) -> UniverseEntry:
    return next(e for e in UNIVERSE.entries if e.key == key)


def synthetic(properties: tuple[AwkwardProperty, ...]) -> UniverseEntry:
    """An entry with the awkward property but none of the facts it implies."""
    return UniverseEntry(
        key="synthetic",
        entity_name="Synthetic plc",
        market=Market.UK,
        mic="XLON",
        quote_currency="GBX",
        reporting_currency="GBP",
        identifiers=(Identifier(kind="ticker", value="SYN", mic="XLON"),),
        properties=properties,
    )


def actions_page(*actions: dict[str, Any]) -> bytes:
    return json.dumps({"actions": list(actions)}).encode()


def prices_page(rows: list[dict[str, Any]], actions: list[dict[str, Any]] | None = None) -> bytes:
    document: dict[str, Any] = {"rows": rows}
    if actions is not None:
        document["actions"] = actions
    return json.dumps(document).encode()


def daily(start: date, end: date, close: str = "100") -> list[dict[str, Any]]:
    """One row per calendar day — weekends included; the checks care about coverage."""
    rows: list[dict[str, Any]] = []
    day = start
    while day <= end:
        rows.append({"date": day.isoformat(), "close": close})
        day += timedelta(days=7)
    return rows


# --------------------------------------------------------------------------- splits


def test_split_ratios_and_ex_dates_match() -> None:
    findings = SplitRatioAndExDateCheck().run(
        entry("apple"),
        [
            actions_page(
                {"type": "split", "ex_date": "2020-08-31", "new_shares": 4, "old_shares": 1},
                {"type": "split", "ex_date": "2014-06-09", "ratio": "7:1"},
            )
        ],
    )
    assert [f.outcome for f in findings] == [Outcome.PASS, Outcome.PASS]


def test_missing_split_fails_with_the_expectation_quoted() -> None:
    (finding,) = SplitRatioAndExDateCheck().run(
        entry("citigroup"), [actions_page({"type": "dividend", "ex_date": "2011-05-09"})]
    )
    assert finding.outcome is Outcome.FAIL
    assert finding.expected is not None and "1:10" in finding.expected
    assert "missing entirely" in finding.explanation


def test_inverted_ratio_is_reported_as_a_convention_difference() -> None:
    """Citigroup's 1-for-10 stated as 10:1 is a 100x error, and is named as such."""
    (finding,) = SplitRatioAndExDateCheck().run(
        entry("citigroup"),
        [
            actions_page(
                {"type": "split", "ex_date": "2011-05-09", "new_shares": 10, "old_shares": 1}
            )
        ],
    )
    assert finding.outcome is Outcome.FAIL
    assert "inverted" in finding.explanation
    assert "old:new" in finding.explanation


def test_split_on_the_wrong_ex_date_is_distinguished_from_a_missing_split() -> None:
    (finding, _) = SplitRatioAndExDateCheck().run(
        entry("apple"),
        [
            actions_page(
                {"type": "split", "ex_date": "2014-06-11", "new_shares": 7, "old_shares": 1},
                {"type": "split", "ex_date": "2020-08-31", "new_shares": 4, "old_shares": 1},
            )
        ],
    )
    assert finding.outcome is Outcome.FAIL
    assert "wrong ex-date" in finding.explanation


def test_split_without_a_usable_ratio_fails() -> None:
    (finding,) = SplitRatioAndExDateCheck().run(
        entry("citigroup"), [actions_page({"type": "split", "ex_date": "2011-05-09"})]
    )
    assert finding.outcome is Outcome.FAIL
    assert "no usable ratio" in finding.explanation


def test_unparseable_payload_fails_with_evidence_instead_of_crashing() -> None:
    (finding,) = SplitRatioAndExDateCheck().run(entry("citigroup"), [b"<html>404</html>"])
    assert finding.outcome is Outcome.FAIL
    assert finding.observed is not None and "not valid JSON" in finding.observed


def test_entry_without_the_fact_is_not_applicable_never_a_pass() -> None:
    (finding,) = SplitRatioAndExDateCheck().run(
        synthetic((AwkwardProperty.SPLIT,)), [actions_page()]
    )
    assert finding.outcome is Outcome.NOT_APPLICABLE


# ------------------------------------------------------------------------ dividends


def test_special_dividend_matches() -> None:
    (finding,) = DividendAmountAndExDateCheck().run(
        entry("microsoft"),
        [
            actions_page(
                {
                    "type": "dividend",
                    "ex_date": "2004-11-15",
                    "amount": "3.00",
                    "currency": "USD",
                    "special": True,
                }
            )
        ],
    )
    assert finding.outcome is Outcome.PASS


def test_silently_omitted_special_dividend_fails() -> None:
    (finding,) = DividendAmountAndExDateCheck().run(
        entry("microsoft"),
        [actions_page({"type": "dividend", "ex_date": "2004-11-16", "amount": "0.08"})],
    )
    assert finding.outcome is Outcome.FAIL
    assert "special dividend is absent" in finding.explanation


def test_gbp_quoted_dividend_reconciles_against_a_gbx_expectation() -> None:
    """50.93p declared as GBP 0.5093 is correct data in another unit, and passes."""
    (finding,) = DividendAmountAndExDateCheck().run(
        entry("tesco"),
        [
            actions_page(
                {
                    "type": "dividend",
                    "ex_date": "2021-02-15",
                    "amount": "0.5093",
                    "currency": "GBP",
                    "special": True,
                }
            )
        ],
    )
    assert finding.outcome is Outcome.PASS
    assert "converted" in finding.explanation


def test_pence_mislabelled_as_pounds_is_a_unit_failure_not_a_numeric_one() -> None:
    (finding,) = DividendAmountAndExDateCheck().run(
        entry("tesco"),
        [
            actions_page(
                {"type": "dividend", "ex_date": "2021-02-15", "amount": "50.93", "currency": "GBP"}
            )
        ],
    )
    assert finding.outcome is Outcome.FAIL
    assert "unit mismatch" in finding.explanation
    assert "factor of 100" in finding.explanation


def test_gbp_spelled_lowercase_p_is_read_as_pence() -> None:
    """`GBp` is pence. Upper-casing it silently would turn this pass into a 100x error."""
    (finding,) = DividendAmountAndExDateCheck().run(
        entry("tesco"),
        [
            actions_page(
                {"type": "dividend", "ex_date": "2021-02-15", "amount": "50.93", "currency": "GBp"}
            )
        ],
    )
    assert finding.outcome is Outcome.PASS


def test_unstated_unit_with_a_factor_of_100_gap_is_a_unit_failure() -> None:
    (finding,) = DividendAmountAndExDateCheck().run(
        entry("tesco"),
        [actions_page({"type": "dividend", "ex_date": "2021-02-15", "amount": "0.5093"})],
    )
    assert finding.outcome is Outcome.FAIL
    assert "states no unit" in finding.explanation


def test_failure_against_an_unverified_expectation_carries_the_review_flag() -> None:
    """Tesco's 2021 special is flagged needs_verification in the universe."""
    (finding,) = DividendAmountAndExDateCheck().run(
        entry("tesco"), [actions_page({"type": "dividend", "ex_date": "2019-01-01"})]
    )
    assert finding.outcome is Outcome.FAIL
    assert finding.explanation.startswith(EXPECTATION_REVIEW_PREFIX)
    assert "re-verified" in finding.explanation


def test_matching_an_unverified_expectation_passes_without_the_flag() -> None:
    (finding,) = DividendAmountAndExDateCheck().run(
        entry("tesco"),
        [
            actions_page(
                {"type": "dividend", "ex_date": "2021-02-15", "amount": "50.93", "currency": "GBX"}
            )
        ],
    )
    assert finding.outcome is Outcome.PASS
    assert EXPECTATION_REVIEW_PREFIX not in finding.explanation


def test_dividend_check_is_not_applicable_without_a_dividend_fact() -> None:
    (finding,) = DividendAmountAndExDateCheck().run(entry("sap"), [actions_page()])
    assert finding.outcome is Outcome.NOT_APPLICABLE


def test_unit_conversion_table() -> None:
    assert unit_conversion("GBX", "GBP") == Decimal("0.01")
    assert unit_conversion("GBP", "GBX") == Decimal(100)
    assert unit_conversion("USD", "USD") == Decimal(1)
    assert unit_conversion("USD", "GBP") is None


# ------------------------------------------------------------------- delisted history


def test_delisted_history_runs_to_the_delisting_date() -> None:
    (finding,) = DelistedPriceHistoryCheck().run(
        entry("carillion"),
        [prices_page([{"date": "2018-01-12", "close": "14.2"}])],
    )
    assert finding.outcome is Outcome.PASS
    assert finding.observed is not None and "2018-01-12" in finding.observed


def test_truncated_delisted_history_reports_the_shortfall_in_days() -> None:
    (finding,) = DelistedPriceHistoryCheck().run(
        entry("carillion"),
        [prices_page([{"date": "2017-10-02", "close": "45.0"}])],
    )
    assert finding.outcome is Outcome.FAIL
    assert "105 days short" in finding.explanation
    assert finding.observed is not None and "close=45.0" in finding.observed


def test_absent_delisted_security_fails_differently_from_a_truncated_one() -> None:
    (finding,) = DelistedPriceHistoryCheck().run(entry("thomas-cook"), [prices_page([])])
    assert finding.outcome is Outcome.FAIL
    assert "no price history at all" in finding.explanation


def test_prices_past_the_delisting_date_are_reported_as_fabricated() -> None:
    (finding,) = DelistedPriceHistoryCheck().run(
        entry("carillion"),
        [prices_page([{"date": "2018-03-01", "close": "1.0"}])],
    )
    assert finding.outcome is Outcome.FAIL
    assert "past the delisting date" in finding.explanation


def test_acquisition_without_a_delisting_fact_is_not_applicable() -> None:
    (finding,) = DelistedPriceHistoryCheck().run(entry("morrisons"), [prices_page([])])
    assert finding.outcome is Outcome.NOT_APPLICABLE


# --------------------------------------------------------------------------- depth


def test_history_depth_passes_with_two_decades() -> None:
    (finding,) = PriceHistoryDepthCheck().run(
        entry("shell"), [prices_page(daily(date(1995, 1, 3), date(2026, 1, 2)))]
    )
    assert finding.outcome is Outcome.PASS


def test_shallow_history_fails_and_reports_the_earliest_date() -> None:
    (finding,) = PriceHistoryDepthCheck().run(
        entry("shell"), [prices_page(daily(date(2019, 1, 3), date(2026, 1, 2)))]
    )
    assert finding.outcome is Outcome.FAIL
    assert finding.observed is not None and "2019-01-03" in finding.observed


# ------------------------------------------------------------------ raw vs adjusted


def split_series(adjust: bool = True, factor: str = "4") -> bytes:
    """Apple's 4:1: adjusted closes before the ex-date are a quarter of raw."""
    divisor = Decimal(factor)
    rows = []
    for day, close in (
        ("2020-08-27", "500"),
        ("2020-08-28", "504"),
        ("2020-08-31", "125"),
        ("2020-09-01", "130"),
    ):
        raw = Decimal(close)
        adjusted = raw / divisor if adjust and day < "2020-08-31" else raw
        rows.append({"date": day, "close": str(raw), "adjusted_close": str(adjusted)})
    return prices_page(
        rows, [{"type": "split", "ex_date": "2020-08-31", "new_shares": 4, "old_shares": 1}]
    )


def test_adjusted_series_reconciles_with_the_providers_own_actions() -> None:
    (finding,) = RawVersusAdjustedCheck().run(entry("apple"), [split_series()])
    assert finding.outcome is Outcome.PASS


def test_irreconcilable_adjusted_series_fails_and_reports_the_error() -> None:
    (finding,) = RawVersusAdjustedCheck().run(entry("apple"), [split_series(factor="7")])
    assert finding.outcome is Outcome.FAIL
    assert finding.observed is not None and "max relative error" in finding.observed


def test_adjusted_identical_to_raw_despite_actions_fails() -> None:
    (finding,) = RawVersusAdjustedCheck().run(entry("apple"), [split_series(adjust=False)])
    assert finding.outcome is Outcome.FAIL
    assert "copy of the raw close" in finding.explanation


def test_dividend_adjustment_reconciles() -> None:
    payload = prices_page(
        [
            {"date": "2004-11-12", "close": "100", "adjusted_close": "97"},
            {"date": "2004-11-15", "close": "97", "adjusted_close": "97"},
        ],
        [{"type": "dividend", "ex_date": "2004-11-15", "amount": "3.00", "currency": "USD"}],
    )
    (finding,) = RawVersusAdjustedCheck().run(entry("microsoft"), [payload])
    assert finding.outcome is Outcome.PASS


def test_payload_without_an_adjusted_series_is_not_applicable() -> None:
    (finding,) = RawVersusAdjustedCheck().run(
        entry("apple"),
        [prices_page([{"date": "2020-08-31", "close": "125"}], [{"type": "split"}])],
    )
    assert finding.outcome is Outcome.NOT_APPLICABLE
    assert "no adjusted series" in finding.explanation


def test_payload_without_actions_is_not_applicable() -> None:
    (finding,) = RawVersusAdjustedCheck().run(
        entry("apple"),
        [prices_page([{"date": "2020-08-31", "close": "125", "adjusted_close": "124"}])],
    )
    assert finding.outcome is Outcome.NOT_APPLICABLE
    assert "no corporate-action records" in finding.explanation


# ----------------------------------------------------------------- ticker continuity


def continuous_rows() -> list[dict[str, Any]]:
    return [
        {"date": "2022-01-21", "close": "1600"},
        {"date": "2022-01-24", "close": "1610"},
        {"date": "2022-01-25", "close": "1620"},
        {"date": "2022-01-26", "close": "1630"},
    ]


def test_price_history_spans_a_ticker_change() -> None:
    (finding,) = TickerChangeContinuityCheck().run(entry("shell"), [prices_page(continuous_rows())])
    assert finding.outcome is Outcome.PASS


def test_history_that_stops_at_the_rename_fails() -> None:
    rows = [r for r in continuous_rows() if r["date"] < "2022-01-25"]
    (finding,) = TickerChangeContinuityCheck().run(entry("shell"), [prices_page(rows)])
    assert finding.outcome is Outcome.FAIL
    assert "does not span the ticker change" in finding.explanation


def test_gap_across_the_rename_fails() -> None:
    rows = [
        {"date": "2022-01-04", "close": "1600"},
        {"date": "2022-02-15", "close": "1630"},
    ]
    (finding,) = TickerChangeContinuityCheck().run(entry("shell"), [prices_page(rows)])
    assert finding.outcome is Outcome.FAIL
    assert "hole spans the ticker change" in finding.explanation


def test_duplicate_dates_across_the_rename_fail() -> None:
    rows = [*continuous_rows(), {"date": "2022-01-25", "close": "1621"}]
    (finding,) = TickerChangeContinuityCheck().run(entry("shell"), [prices_page(rows)])
    assert finding.outcome is Outcome.FAIL
    assert "more than once" in finding.explanation


def test_unexplained_jump_across_the_rename_fails() -> None:
    rows = [
        {"date": "2022-01-24", "close": "1610"},
        {"date": "2022-01-25", "close": "800"},
    ]
    (finding,) = TickerChangeContinuityCheck().run(entry("shell"), [prices_page(rows)])
    assert finding.outcome is Outcome.FAIL
    assert "no corporate action in the payload to explain it" in finding.explanation


def test_jump_explained_by_an_action_in_the_payload_passes() -> None:
    rows = [
        {"date": "2022-01-24", "close": "1610"},
        {"date": "2022-01-25", "close": "800"},
    ]
    payload = prices_page(
        rows, [{"type": "split", "ex_date": "2022-01-25", "new_shares": 1, "old_shares": 2}]
    )
    (finding,) = TickerChangeContinuityCheck().run(entry("shell"), [payload])
    assert finding.outcome is Outcome.PASS
    assert "explains the step" in finding.explanation


# ------------------------------------------------------------------------ wiring


def test_checks_declare_their_datasets_and_properties() -> None:
    shell, apple = entry("shell"), entry("apple")
    assert DelistedPriceHistoryCheck().applies_to(entry("carillion"), Dataset.PRICES)
    assert not DelistedPriceHistoryCheck().applies_to(apple, Dataset.PRICES)
    assert not DelistedPriceHistoryCheck().applies_to(entry("carillion"), Dataset.FUNDAMENTALS)
    assert TickerChangeContinuityCheck().applies_to(shell, Dataset.PRICES)
    assert SplitRatioAndExDateCheck().applies_to(apple, Dataset.CORPORATE_ACTIONS)
    # properties = None: applicability is decided by the entry's facts, not its tags.
    assert DividendAmountAndExDateCheck().applies_to(shell, Dataset.CORPORATE_ACTIONS)


@pytest.fixture
def clean_registry() -> object:
    checks_module.clear_registry()
    yield None
    checks_module.clear_registry()
    register_all()


def test_registration_is_idempotent(clean_registry: object) -> None:
    register_all()
    register_all()  # would raise if it double-registered
    names = {c.name for c in checks_module.registered_checks()}
    assert names == {c.name for c in CORPORATE_ACTION_CHECKS}
