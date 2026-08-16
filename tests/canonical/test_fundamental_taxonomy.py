import json
from pathlib import Path

import pytest

from trp.canonical.fundamentals import taxonomy as taxonomy_module
from trp.canonical.fundamentals.taxonomy import (
    LineItemTaxonomy,
    SignConvention,
    UnitKind,
    UnknownCanonicalItemError,
    default_taxonomy,
    load_all_mapping_tables,
    load_taxonomy,
)
from trp.domain.fundamentals import StatementType

VALUE_AND_QUALITY_ITEMS = (
    "revenue",
    "cost_of_sales",
    "gross_profit",
    "operating_profit",
    "net_income",
    "eps_basic",
    "total_assets",
    "total_equity",
    "total_debt",
    "cash_and_equivalents",
    "operating_cash_flow",
    "capital_expenditure",
    "free_cash_flow",
)


def test_packaged_taxonomy_covers_all_three_statements_with_full_entries() -> None:
    taxonomy = default_taxonomy()
    assert taxonomy.version == "1.0"
    for statement in StatementType:
        assert taxonomy.for_statement(statement), f"no items on {statement.value}"
    for name in VALUE_AND_QUALITY_ITEMS:
        item = taxonomy.item(name)  # raises if absent
        assert item.definition.strip(), f"{name} has no definition"
        assert item.unit_kind in UnitKind
        assert item.sign_convention in SignConvention


def test_taxonomy_is_data_not_code() -> None:
    """The canonical names live in the JSON file, not as constants in the module.

    The point of the ticket: the taxonomy is reviewable in a diff and editable without a
    code change. If a name ever needs to appear in this module, that is the moment the
    design has slipped.
    """
    source = Path(taxonomy_module.__file__).read_text("utf-8")
    for name in default_taxonomy().names:
        assert name not in source, f"{name} is hard-coded in taxonomy.py; it belongs in the data"


def test_unknown_canonical_name_is_rejected_loudly() -> None:
    taxonomy = default_taxonomy()
    with pytest.raises(UnknownCanonicalItemError, match="ebitda"):
        taxonomy.item("ebitda")
    assert taxonomy.get("ebitda") is None  # the tolerant lookup, for callers that mean it


def test_sign_conventions_are_stated_for_the_items_that_disagree_across_providers() -> None:
    taxonomy = default_taxonomy()
    for outflow in ("capital_expenditure", "dividends_paid", "share_buybacks"):
        assert taxonomy.item(outflow).sign_convention is SignConvention.NEGATIVE
    # Costs are carried as positive magnitudes and subtracted by whoever uses them.
    assert taxonomy.item("cost_of_sales").sign_convention is SignConvention.POSITIVE
    assert taxonomy.item("total_equity").sign_convention is SignConvention.EITHER


def test_unit_kinds_separate_money_from_counts() -> None:
    taxonomy = default_taxonomy()
    assert taxonomy.item("shares_outstanding").unit_kind is UnitKind.SHARE_COUNT
    assert not taxonomy.item("shares_outstanding").unit_kind.is_monetary
    assert taxonomy.item("eps_basic").unit_kind is UnitKind.PER_SHARE_AMOUNT
    assert taxonomy.item("eps_basic").unit_kind.is_monetary  # converts like money, per share
    assert taxonomy.item("revenue").unit_kind is UnitKind.CURRENCY_AMOUNT


def test_duplicate_canonical_names_are_rejected_at_load(tmp_path: Path) -> None:
    payload = {
        "version": "1.0",
        "items": [
            {
                "name": "revenue",
                "statement": "income",
                "unit_kind": "currency_amount",
                "sign_convention": "positive",
                "definition": "Turnover for the period.",
            },
            {
                "name": "revenue",
                "statement": "income",
                "unit_kind": "currency_amount",
                "sign_convention": "positive",
                "definition": "Turnover again, differently defined.",
            },
        ],
    }
    path = tmp_path / "taxonomy.json"
    path.write_text(json.dumps(payload))
    with pytest.raises(ValueError, match="duplicate canonical line items"):
        load_taxonomy(path)


def test_taxonomy_version_is_recorded_and_required(tmp_path: Path) -> None:
    path = tmp_path / "taxonomy.json"
    path.write_text(json.dumps({"items": []}))
    with pytest.raises(ValueError):  # pydantic reports both missing fields at once
        load_taxonomy(path)

    assert (
        LineItemTaxonomy.model_validate_json(
            Path(taxonomy_module.__file__)
            .parent.joinpath("line_item_taxonomy.json")
            .read_text("utf-8")
        ).version
        == default_taxonomy().version
    )


def test_every_shipped_mapping_table_validates_against_the_taxonomy() -> None:
    """Shipped mapping files are loaded and cross-checked, not merely present."""
    tables = load_all_mapping_tables()
    assert set(tables) >= {"eodhd", "fmp"}
    taxonomy = default_taxonomy()
    for provider, table in tables.items():
        assert table.taxonomy_version == taxonomy.version, provider
        for entry in table.mapped_entries:
            assert entry.canonical is not None
            assert taxonomy.item(entry.canonical).statement == entry.statement
