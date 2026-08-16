import json
from pathlib import Path

import pytest
from pydantic import ValidationError

from trp.bakeoff.universe.loader import (
    SPEC_PATH,
    AwkwardProperty,
    Market,
    RestatementFact,
    UniverseEntry,
    ValidationUniverse,
    load_universe,
)


@pytest.fixture(scope="module")
def universe() -> ValidationUniverse:
    return load_universe()


def test_versioned_and_deterministic(universe: ValidationUniverse) -> None:
    assert universe.version == "2026-08-16.1"
    keys = [e.key for e in universe.entries]
    assert keys == sorted(keys)
    assert load_universe().entries == universe.entries  # cached + stable


def test_every_required_category_is_represented(universe: ValidationUniverse) -> None:
    for prop in AwkwardProperty:
        assert universe.by_property(prop), f"no entry exercises {prop.value}"
    for market in Market:
        assert universe.by_market(market), f"no entry for market {market.value}"


def test_identifier_checksums_are_valid_or_explicitly_unknown(
    universe: ValidationUniverse,
) -> None:
    # Construction already validates check digits; here we assert unknowns are explicit.
    for entry in universe.entries:
        for identifier in entry.identifiers:
            assert identifier.kind in {"isin", "sedol", "ticker"}
            if identifier.value is None:
                assert identifier.kind in {"isin", "sedol"}  # a null ticker is meaningless


def test_every_fact_has_a_source_and_verification_date(universe: ValidationUniverse) -> None:
    for entry in universe.entries:
        for fact in entry.facts:
            assert fact.source
            assert fact.verified_on is not None


def test_restatement_entry_supports_the_timetravel_suites(universe: ValidationUniverse) -> None:
    (tesco,) = universe.by_property(AwkwardProperty.RESTATEMENT)
    restatement = next(f for f in tesco.facts if isinstance(f, RestatementFact))
    # The fields the QNT-022/025 timetravel fixtures need:
    assert restatement.original_available < restatement.restatement_available
    assert restatement.original_value != restatement.restated_value
    assert restatement.line_item == "trading_profit_guidance"


def test_schema_rejects_fact_after_delisting(universe: ValidationUniverse) -> None:
    carillion = next(e for e in universe.entries if e.key == "carillion")
    payload = carillion.model_dump(mode="json")
    payload["facts"].append(
        {
            "fact": "dividend",
            "ex_date": "2019-01-01",  # after the 2018 failure
            "amount": "1",
            "unit": "GBX",
            "source": "impossible",
            "verified_on": "2026-08-16",
        }
    )
    with pytest.raises(ValidationError, match="on or after delisting"):
        UniverseEntry.model_validate(payload)


def test_schema_rejects_unknown_property_and_bad_isin(tmp_path: Path) -> None:
    spec = json.loads(SPEC_PATH.read_text())
    spec["entries"][0]["properties"] = ["long_lived", "meme_stock"]
    with pytest.raises(ValidationError):
        ValidationUniverse.model_validate(spec)

    spec = json.loads(SPEC_PATH.read_text())
    spec["entries"][0]["identifiers"][0]["value"] = "US0378331004"  # bad check digit
    with pytest.raises(ValidationError, match="check digit"):
        ValidationUniverse.model_validate(spec)


def test_uk_dividend_expectations_state_their_unit(universe: ValidationUniverse) -> None:
    for entry in universe.by_market(Market.UK):
        for fact in entry.facts:
            unit = getattr(fact, "unit", None)
            if unit is not None:
                assert unit in {"GBX", "GBP"}, f"{entry.key}: ambiguous unit {unit}"
