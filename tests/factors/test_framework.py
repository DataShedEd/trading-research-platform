import json
from datetime import UTC, date, datetime
from decimal import Decimal
from pathlib import Path

import pytest

from tests.factors.test_returns import daily_bars
from trp.domain.corporate_actions import Dividend
from trp.domain.identifiers import new_security_id
from trp.factors.compute import (
    ComputeContext,
    compute_factor,
    registered_transforms,
    write_factor_values,
)
from trp.factors.definition import (
    DefinitionError,
    FactorDefinition,
    compute_content_hash,
)
from trp.factors.registry import FactorRegistry

AS_OF = datetime(2022, 1, 1, tzinfo=UTC)


def definition_body(**overrides: object) -> dict[str, object]:
    body: dict[str, object] = {
        "name": "momentum_test",
        "version": 1,
        "description": "12-1 total-return momentum (test definition)",
        "inputs": ["prices", "corporate_actions"],
        "transform": "window_total_return",
        "parameters": {"months": 12, "skip_months": 1, "basis": "total"},
    }
    body.update(overrides)
    body["content_hash"] = compute_content_hash(body)
    return body


class TestDefinition:
    def test_valid_definition_loads(self) -> None:
        definition = FactorDefinition.model_validate(definition_body())
        assert definition.tag() == "momentum_test@v1"

    def test_in_place_edit_detected(self) -> None:
        body = definition_body()
        body["parameters"] = {"months": 6, "skip_months": 1, "basis": "total"}  # edited...
        # ...but content_hash left as it was: the mutation the framework must catch.
        with pytest.raises(ValueError, match="edited in place — bump the version"):
            FactorDefinition.model_validate(body)

    def test_description_changes_are_cosmetic(self) -> None:
        body = definition_body()
        body["description"] = "reworded"
        FactorDefinition.model_validate(body)  # hash unchanged by design

    def test_unknown_input_dataset_rejected(self) -> None:
        with pytest.raises(ValueError, match="unknown input dataset"):
            FactorDefinition.model_validate(definition_body(inputs=["vibes"]))


class TestRegistry:
    def write(self, directory: Path, *bodies: dict[str, object]) -> None:
        for index, body in enumerate(bodies):
            (directory / f"def{index}.json").write_text(json.dumps(body))

    def test_load_get_latest_and_specific(self, tmp_path: Path) -> None:
        v2 = definition_body(version=2, parameters={"months": 6, "skip_months": 1})
        self.write(tmp_path, definition_body(), v2)
        registry = FactorRegistry.load(tmp_path)
        assert registry.get("momentum_test").version == 2  # latest by default
        assert registry.get("momentum_test", 1).parameters["months"] == 12
        with pytest.raises(DefinitionError, match="no version 3"):
            registry.get("momentum_test", 3)
        with pytest.raises(DefinitionError, match="no factor named"):
            registry.get("value_test")

    def test_duplicate_version_rejected(self, tmp_path: Path) -> None:
        self.write(tmp_path, definition_body(), definition_body())
        with pytest.raises(DefinitionError, match="versions are immutable"):
            FactorRegistry.load(tmp_path)

    def test_unknown_transform_rejected_at_load(self, tmp_path: Path) -> None:
        self.write(tmp_path, definition_body(transform="astrology"))
        with pytest.raises(DefinitionError, match="unknown transform 'astrology'"):
            FactorRegistry.load(tmp_path)

    def test_transform_registry_is_enumerable(self) -> None:
        assert "window_total_return" in registered_transforms()


class TestCompute:
    def context(self) -> ComputeContext:
        sid = new_security_id()
        bars = daily_bars(
            sid, date(2020, 11, 1), date(2021, 12, 31), "1000", {date(2021, 6, 1): "1100"}
        )
        return ComputeContext(
            security_ids=[sid],
            end=date(2021, 12, 31),
            as_of=AS_OF,
            bars=bars,
            input_versions={"prices": "ingest-2026-08-18"},
        )

    def test_values_are_tagged_and_deterministic(self, tmp_path: Path) -> None:
        definition = FactorDefinition.model_validate(definition_body())
        context = self.context()
        first = compute_factor(definition, context)
        second = compute_factor(definition, context)
        assert first.equals(second)  # deterministic
        row = first.to_dicts()[0]
        assert row["factor"] == "momentum_test"
        assert row["factor_version"] == 1
        assert row["input_versions"] == "prices=ingest-2026-08-18"
        assert row["value"] == pytest.approx(0.10)  # 1000 -> 1100 before the skip month

        target = write_factor_values(first, tmp_path)
        assert "name=momentum_test" in str(target) and "version=1" in str(target)
        with pytest.raises(DefinitionError, match="never overwritten"):
            write_factor_values(first, tmp_path)

    def test_two_versions_coexist_in_the_store(self, tmp_path: Path) -> None:
        context = self.context()
        v1 = FactorDefinition.model_validate(definition_body())
        v2 = FactorDefinition.model_validate(
            definition_body(version=2, parameters={"months": 6, "skip_months": 1})
        )
        write_factor_values(compute_factor(v1, context), tmp_path)
        write_factor_values(compute_factor(v2, context), tmp_path)
        assert (tmp_path / "name=momentum_test" / "version=1").exists()
        assert (tmp_path / "name=momentum_test" / "version=2").exists()

    def test_untagged_frames_cannot_be_written(self, tmp_path: Path) -> None:
        import polars as pl

        with pytest.raises(DefinitionError, match="untagged"):
            write_factor_values(pl.DataFrame({"security_id": ["x"], "value": [1.0]}), tmp_path)


@pytest.mark.timetravel
def test_compute_surface_propagates_as_of() -> None:
    sid = new_security_id()
    bars = daily_bars(sid, date(2020, 6, 1), date(2021, 12, 31), "1000")
    late_dividend = Dividend(
        security_id=sid,
        ex_date=date(2021, 3, 1),
        source="t",
        available_at=datetime(2021, 9, 1, tzinfo=UTC),  # published in September
        amount=Decimal("50"),
        currency="GBX",
    )
    definition = FactorDefinition.model_validate(definition_body())

    def value_at(as_of: datetime) -> float:
        context = ComputeContext(
            security_ids=[sid],
            end=date(2021, 12, 31),
            as_of=as_of,
            bars=bars,
            actions=[late_dividend],
        )
        return compute_factor(definition, context).to_dicts()[0]["value"]

    before = value_at(datetime(2021, 8, 1, tzinfo=UTC))
    after = value_at(datetime(2021, 10, 1, tzinfo=UTC))
    assert before == pytest.approx(0.0)  # the dividend is not knowable yet
    assert after == pytest.approx(1 / 0.95 - 1)
