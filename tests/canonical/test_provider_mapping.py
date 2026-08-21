import json
from datetime import UTC, date, datetime
from decimal import Decimal
from pathlib import Path

import pytest

from tests.fixtures.provider_payload import MAPPINGS_DIRECTORY, STUB_PROVIDER, stub_payload
from trp.canonical.fundamentals.normalisation import (
    DuplicateProviderItemError,
    NormalisationResult,
    NormalisedLineItem,
    ProviderLineItem,
    ProviderMismatchError,
    UnmappedLineItem,
    UnmappedReason,
    normalise_line_items,
    sign_violations,
    to_fundamental_value,
)
from trp.canonical.fundamentals.taxonomy import (
    MappingTable,
    MappingTableError,
    ReviewStatus,
    Sign,
    UnitKind,
    UnknownProviderError,
    load_mapping_table,
)
from trp.domain.fundamentals import PeriodType, StatementType
from trp.domain.identifiers import new_security_id

BASE_ENTRY = {
    "provider_item": "turnover",
    "statement": "income",
    "canonical": "revenue",
    "review_status": "verified",
}


@pytest.fixture
def stub_table() -> MappingTable:
    return load_mapping_table(STUB_PROVIDER, directory=MAPPINGS_DIRECTORY)


def normalised(table: MappingTable) -> NormalisationResult:
    return normalise_line_items(stub_payload(), provider=STUB_PROVIDER, mappings=table)


def write_table(directory: Path, provider: str, **overrides: object) -> Path:
    payload: dict[str, object] = {
        "provider": provider,
        "version": "1.0",
        "taxonomy_version": "1.1",
        "entries": [dict(BASE_ENTRY)],
    }
    payload.update(overrides)
    path = directory / f"{provider}.json"
    path.write_text(json.dumps(payload))
    return path


def test_full_payload_maps_deterministically(stub_table: MappingTable) -> None:
    first, second = normalised(stub_table), normalised(stub_table)
    assert first == second
    assert first.model_dump_json() == second.model_dump_json()  # byte-identical, not just equal

    values = {item.line_item: item.value for item in first.mapped}
    assert values == {
        "revenue": Decimal("6420000000"),
        "cost_of_sales": Decimal("4100000000"),
        "net_income": Decimal("512000000"),
        "total_assets": Decimal("9310000000"),
        "shares_outstanding": Decimal("1850000000"),
        "operating_cash_flow": Decimal("1130000000"),
        "capital_expenditure": Decimal("-480000000"),
    }
    # Sorted output, independent of the payload's deliberately jumbled order.
    assert [m.sort_key for m in first.mapped] == sorted(m.sort_key for m in first.mapped)


def test_capital_expenditure_takes_the_documented_canonical_sign(stub_table: MappingTable) -> None:
    """The fixture provider reports capex positive; the mapping's sign flag flips it."""
    capex = normalised(stub_table).item("capital_expenditure")
    assert capex is not None
    assert capex.sign_applied is Sign.FLIP
    assert capex.value == Decimal("-480000000")
    assert not sign_violations(normalised(stub_table))  # nothing contradicts its convention


def test_a_wrong_sign_flag_shows_up_as_data_rather_than_a_plausible_number(
    stub_table: MappingTable,
) -> None:
    unflipped = MappingTable.model_validate(
        {
            **stub_table.model_dump(mode="json"),
            "entries": [
                {**entry, "sign": "as_reported"}
                if entry["provider_item"] == "capitalExpenditure"
                else entry
                for entry in stub_table.model_dump(mode="json")["entries"]
            ],
        }
    )
    violations = sign_violations(normalised(unflipped))
    assert [v.line_item for v in violations] == ["capital_expenditure"]


def test_unmapped_items_are_preserved_flagged_and_counted(stub_table: MappingTable) -> None:
    result = normalised(stub_table)

    by_name = {u.provider_item: u for u in result.unmapped}
    unknown = by_name["adjustedEbitdaMargin"]
    assert unknown.reason is UnmappedReason.NO_MAPPING
    assert unknown.value == Decimal("0.184")  # raw value, untouched
    assert unknown.statement is StatementType.INCOME

    excluded = by_name["profitForTheYear"]  # the cash-flow one, deliberately refused
    assert excluded.reason is UnmappedReason.DELIBERATELY_EXCLUDED
    assert excluded.statement is StatementType.CASH_FLOW
    assert "second net_income" in excluded.note

    summary = result.summary
    assert summary.items_in == len(stub_payload())
    assert (summary.mapped, summary.unmapped_no_mapping, summary.deliberately_excluded) == (7, 1, 1)
    assert summary.mapped_verified == 7 and summary.mapped_provisional == 0

    # And nothing landed under a canonical name it was not mapped to.
    assert "adjustedEbitdaMargin" not in {m.provider_item for m in result.mapped}
    assert len({m.line_item for m in result.mapped}) == len(result.mapped)


def test_the_same_provider_name_on_two_statements_resolves_separately(
    stub_table: MappingTable,
) -> None:
    result = normalised(stub_table)
    income = result.item("net_income")
    assert income is not None and income.provider_item == "profitForTheYear"
    assert income.statement is StatementType.INCOME
    assert [u.statement for u in result.unmapped if u.provider_item == "profitForTheYear"] == [
        StatementType.CASH_FLOW
    ]


def test_a_mapped_item_becomes_a_fundamental_value_with_the_canonical_line_item(
    stub_table: MappingTable,
) -> None:
    revenue = normalised(stub_table).item("revenue")
    assert revenue is not None
    available_at = datetime(2020, 3, 12, 7, 0, tzinfo=UTC)
    record = to_fundamental_value(
        revenue,
        security_id=new_security_id(),
        period_end=date(2019, 12, 31),
        period_type=PeriodType.ANNUAL,
        currency="GBP",
        available_at=available_at,
        source="fixture:stub",
    )
    assert record.line_item == "revenue"  # canonical, not "turnover"
    assert record.statement is StatementType.INCOME
    assert record.value == Decimal("6420000000")
    assert record.currency == "GBP"  # reporting currency, unconverted (QNT-023)
    assert record.available_at == available_at  # the caller's, not one normalisation invented
    assert record.revision_sequence == 0


def test_normalisation_neither_invents_nor_alters_a_timestamp(stub_table: MappingTable) -> None:
    for model in (ProviderLineItem, NormalisedLineItem, UnmappedLineItem, NormalisationResult):
        for name, field in model.model_fields.items():
            assert field.annotation not in (datetime, date), f"{model.__name__}.{name} is temporal"
    assert "datetime.now" not in Path(normalise_line_items.__globals__["__file__"]).read_text(
        "utf-8"
    )


def test_versions_are_recorded_on_every_mapped_row(stub_table: MappingTable) -> None:
    result = normalised(stub_table)
    assert (result.taxonomy_version, result.mapping_version) == ("1.1", "1.0")
    for item in result.mapped:
        assert item.taxonomy_version == "1.1"
        assert item.mapping_version == stub_table.version
        assert item.provider == STUB_PROVIDER


def test_a_repeated_payload_item_raises_rather_than_one_of_them_winning(
    stub_table: MappingTable,
) -> None:
    doubled = [
        *stub_payload(),
        ProviderLineItem(
            statement=StatementType.INCOME, name="turnover", value=Decimal("6420000001")
        ),
    ]
    with pytest.raises(DuplicateProviderItemError, match="turnover"):
        normalise_line_items(doubled, provider=STUB_PROVIDER, mappings=stub_table)


def test_float_values_are_rejected_not_coerced() -> None:
    with pytest.raises(ValueError, match=r"valid decimal|Decimal"):
        ProviderLineItem(statement=StatementType.INCOME, name="turnover", value=6.42e9)  # type: ignore[arg-type]


def test_a_table_for_another_provider_is_refused(stub_table: MappingTable) -> None:
    with pytest.raises(ProviderMismatchError, match="stub"):
        normalise_line_items(stub_payload(), provider="eodhd", mappings=stub_table)


def test_loader_rejects_an_unknown_canonical_name(tmp_path: Path) -> None:
    write_table(tmp_path, "bad", entries=[{**BASE_ENTRY, "canonical": "turnover_ebitda"}])
    with pytest.raises(MappingTableError, match="turnover_ebitda"):
        load_mapping_table("bad", directory=tmp_path)


def test_loader_rejects_a_duplicate_provider_key(tmp_path: Path) -> None:
    write_table(tmp_path, "bad", entries=[dict(BASE_ENTRY), dict(BASE_ENTRY)])
    with pytest.raises(MappingTableError, match="duplicate provider keys"):
        load_mapping_table("bad", directory=tmp_path)


def test_loader_rejects_two_provider_items_claiming_one_canonical_item(tmp_path: Path) -> None:
    write_table(
        tmp_path,
        "bad",
        entries=[dict(BASE_ENTRY), {**BASE_ENTRY, "provider_item": "totalRevenue"}],
    )
    with pytest.raises(MappingTableError, match="claimed by two provider items"):
        load_mapping_table("bad", directory=tmp_path)


def test_loader_rejects_a_canonical_item_on_the_wrong_statement(tmp_path: Path) -> None:
    write_table(tmp_path, "bad", entries=[{**BASE_ENTRY, "statement": "balance"}])
    with pytest.raises(MappingTableError, match="taxonomy places"):
        load_mapping_table("bad", directory=tmp_path)


def test_loader_rejects_a_table_written_against_another_taxonomy_version(tmp_path: Path) -> None:
    write_table(tmp_path, "bad", taxonomy_version="0.9")
    with pytest.raises(MappingTableError, match=r"taxonomy v0\.9"):
        load_mapping_table("bad", directory=tmp_path)


def test_loader_rejects_an_exclusion_that_is_not_explicit(tmp_path: Path) -> None:
    write_table(tmp_path, "bad", entries=[{**BASE_ENTRY, "canonical": None}])
    with pytest.raises(MappingTableError, match="excluded"):
        load_mapping_table("bad", directory=tmp_path)


def test_loader_rejects_a_file_whose_name_disagrees_with_its_provider(tmp_path: Path) -> None:
    path = write_table(tmp_path, "bad")
    path.write_text(path.read_text("utf-8").replace('"provider": "bad"', '"provider": "other"'))
    with pytest.raises(MappingTableError, match="file name is the key"):
        load_mapping_table("bad", directory=tmp_path)


def test_an_unknown_provider_names_the_ones_that_exist(tmp_path: Path) -> None:
    write_table(tmp_path, "stub")
    with pytest.raises(UnknownProviderError, match="stub"):
        load_mapping_table("nobody", directory=tmp_path)


def test_shipped_eodhd_entries_are_verified_with_evidence() -> None:
    """QNT-097 promoted every mapped entry against 197 captured payloads; the table must
    say so, cite its evidence, and keep the two documented sign flips (capex confirmed
    positive-magnitude in 20,738/20,738 rows; dividendsPaid in 98.8% of 15,064)."""
    table = load_mapping_table("eodhd")
    statuses = {e.review_status for e in table.mapped_entries}
    assert statuses == {ReviewStatus.VERIFIED}
    assert "Verified 2026-08-21" in table.notes
    capex = table.entry(StatementType.CASH_FLOW, "capitalExpenditures")
    assert capex is not None and capex.sign is Sign.FLIP and capex.note
    dividends = table.entry(StatementType.CASH_FLOW, "dividendsPaid")
    assert dividends is not None and dividends.sign is Sign.FLIP and dividends.note


def test_unit_kind_travels_with_the_mapped_item(stub_table: MappingTable) -> None:
    shares = normalised(stub_table).item("shares_outstanding")
    assert shares is not None and shares.unit_kind is UnitKind.SHARE_COUNT
