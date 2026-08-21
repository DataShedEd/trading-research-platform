"""QNT-048: composite scoring — hand fixtures, missing policies, config-only weights."""

import json
import re
from pathlib import Path

import polars as pl
import pytest

import trp.factors as factors_package
from trp.factors.composite import component_specs, validate_composite
from trp.factors.compute import _TRANSFORMS, ComputeContext
from trp.factors.definition import DefinitionError, FactorDefinition, compute_content_hash
from trp.factors.registry import FactorRegistry

REGISTRY = FactorRegistry.load()


def definition(parameters: dict) -> FactorDefinition:  # type: ignore[type-arg]
    body = {
        "name": "test_composite",
        "version": 1,
        "description": "fixture",
        "inputs": ["prices"],
        "transform": "composite",
        "parameters": parameters,
    }
    body["content_hash"] = compute_content_hash(body)
    return FactorDefinition.model_validate(body)


def two_component_params(**overrides: object) -> dict:  # type: ignore[type-arg]
    parameters: dict = {  # type: ignore[type-arg]
        "components": [
            {"name": "alpha", "version": 1, "weight": 2.0},
            {"name": "beta", "version": 1, "weight": 1.0, "direction": -1},
        ],
        "standardise": "zscore",
        "missing_policy": "renormalise",
        "min_components": 1,
    }
    parameters.update(overrides)
    return parameters


class StubRegistry:
    """Feeds the composite transform hand-made component cross-sections."""

    def __init__(self, frames: dict[str, pl.DataFrame]) -> None:
        self._frames = frames

    def get(self, name: str, version: int | None = None) -> FactorDefinition:
        if name not in self._frames:
            raise DefinitionError(f"no factor named {name!r}")
        body = {
            "name": name,
            "version": version or 1,
            "description": "stub",
            "inputs": ["prices"],
            "transform": f"stub_{name}",
            "parameters": {},
        }
        body["content_hash"] = compute_content_hash(body)
        return FactorDefinition.model_validate(body)


def component_frame(values: dict[str, float | None]) -> pl.DataFrame:
    return pl.DataFrame(
        [
            {
                "security_id": sid,
                "status": "ok" if v is not None else "no_data",
                "value": v,
                "warnings": [],
            }
            for sid, v in values.items()
        ],
        schema={
            "security_id": pl.Utf8,
            "status": pl.Utf8,
            "value": pl.Float64,
            "warnings": pl.List(pl.Utf8),
        },
    )


@pytest.fixture
def stubbed(monkeypatch: pytest.MonkeyPatch):  # type: ignore[no-untyped-def]
    """Register stub component transforms and point the composite at a stub registry."""
    frames = {
        "alpha": component_frame({"a": 1.0, "b": 2.0, "c": 3.0}),
        "beta": component_frame({"a": 30.0, "b": 20.0, "c": 10.0}),
    }
    registered = []
    for name, frame in frames.items():
        key = f"stub_{name}"
        if key not in _TRANSFORMS:
            _TRANSFORMS[key] = lambda context, params, f=frame: f
            registered.append(key)
    import trp.factors.registry as registry_module

    monkeypatch.setattr(
        registry_module.FactorRegistry, "load", classmethod(lambda cls: StubRegistry(frames))
    )
    yield frames
    for key in registered:
        _TRANSFORMS.pop(key, None)


def run_composite(parameters: dict, ids: list[str]) -> dict[str, dict]:  # type: ignore[type-arg]
    from datetime import UTC, date, datetime

    from trp.factors.compute import compute_factor

    context = ComputeContext(
        security_ids=ids,  # type: ignore[arg-type]
        end=date(2021, 6, 30),
        as_of=datetime(2021, 7, 1, tzinfo=UTC),
    )
    frame = compute_factor(definition(parameters), context)
    return {row["security_id"]: row for row in frame.iter_rows(named=True)}


def test_two_component_hand_case(stubbed) -> None:  # type: ignore[no-untyped-def]
    """alpha z-scores: a=-1, b=0, c=+1. beta z-scores: a=+1, b=0, c=-1, direction -1
    flips to a=-1, b=0, c=+1. Weights 2 and 1 -> score = (2za + 1zb)/3."""
    result = run_composite(two_component_params(), ["a", "b", "c"])
    assert result["a"]["value"] == pytest.approx((2 * -1 + 1 * -1) / 3)
    assert result["b"]["value"] == pytest.approx(0.0)
    assert result["c"]["value"] == pytest.approx((2 * 1 + 1 * 1) / 3)
    assert result["a"]["components"] == "alpha@1;beta@1"


def test_missing_policy_renormalise(stubbed) -> None:  # type: ignore[no-untyped-def]
    stubbed["beta"] = None  # unused; the stub for beta lacks security d below
    frames_beta = component_frame({"a": 30.0, "b": 20.0, "c": 10.0, "d": None})
    _TRANSFORMS["stub_beta"] = lambda context, params, f=frames_beta: f
    frames_alpha = component_frame({"a": 1.0, "b": 2.0, "c": 3.0, "d": 6.0})
    _TRANSFORMS["stub_alpha"] = lambda context, params, f=frames_alpha: f
    result = run_composite(two_component_params(), ["a", "b", "c", "d"])
    # d has alpha only: renormalised over the single remaining weight -> its own z-score.
    assert result["d"]["status"] == "ok"
    alpha_values = [1.0, 2.0, 3.0, 6.0]
    mean = sum(alpha_values) / 4
    stdev = (sum((v - mean) ** 2 for v in alpha_values) / 3) ** 0.5
    assert result["d"]["value"] == pytest.approx((6.0 - mean) / stdev)
    assert "renormalised" in result["d"]["warnings"][0]


def test_missing_policy_drop(stubbed) -> None:  # type: ignore[no-untyped-def]
    frames_beta = component_frame({"a": 30.0, "b": 20.0, "c": 10.0, "d": None})
    _TRANSFORMS["stub_beta"] = lambda context, params, f=frames_beta: f
    frames_alpha = component_frame({"a": 1.0, "b": 2.0, "c": 3.0, "d": 6.0})
    _TRANSFORMS["stub_alpha"] = lambda context, params, f=frames_alpha: f
    result = run_composite(two_component_params(missing_policy="drop"), ["a", "b", "c", "d"])
    assert result["d"]["status"] == "no_data"
    assert result["a"]["status"] == "ok"


def test_missing_policy_neutral_is_explicit(stubbed) -> None:  # type: ignore[no-untyped-def]
    frames_beta = component_frame({"a": 30.0, "b": 20.0, "c": 10.0, "d": None})
    _TRANSFORMS["stub_beta"] = lambda context, params, f=frames_beta: f
    frames_alpha = component_frame({"a": 1.0, "b": 2.0, "c": 3.0, "d": 6.0})
    _TRANSFORMS["stub_alpha"] = lambda context, params, f=frames_alpha: f
    result = run_composite(two_component_params(missing_policy="neutral"), ["a", "b", "c", "d"])
    assert result["d"]["status"] == "ok"
    assert "neutral for beta@1" in result["d"]["warnings"][0]
    # The missing component contributes 0 at its full weight: (2*z_d + 1*0) / 3.
    alpha_values = [1.0, 2.0, 3.0, 6.0]
    mean = sum(alpha_values) / 4
    stdev = (sum((v - mean) ** 2 for v in alpha_values) / 3) ** 0.5
    assert result["d"]["value"] == pytest.approx(2 * ((6.0 - mean) / stdev) / 3)


def test_minimum_components_enforced(stubbed) -> None:  # type: ignore[no-untyped-def]
    frames_beta = component_frame({"a": 30.0, "b": 20.0, "c": 10.0, "d": None})
    _TRANSFORMS["stub_beta"] = lambda context, params, f=frames_beta: f
    frames_alpha = component_frame({"a": 1.0, "b": 2.0, "c": 3.0, "d": 6.0})
    _TRANSFORMS["stub_alpha"] = lambda context, params, f=frames_alpha: f
    result = run_composite(two_component_params(min_components=2), ["a", "b", "c", "d"])
    assert result["d"]["status"] == "insufficient_data"


def test_unknown_component_version_rejected_at_load() -> None:
    bad = definition(
        {
            "components": [{"name": "momentum_12_1", "version": 99, "weight": 1.0}],
            "standardise": "zscore",
            "missing_policy": "drop",
        }
    )
    with pytest.raises(DefinitionError, match="not in the registry"):
        validate_composite(bad, REGISTRY)


def test_shipped_composite_validates_and_specs_parse() -> None:
    shipped = REGISTRY.get("qvm_equal")
    specs = component_specs(dict(shipped.parameters))
    assert [spec.label for spec in specs] == [
        "momentum_12_1@1",
        "earnings_yield@1",
        "gross_profitability@1",
    ]
    validate_composite(shipped, REGISTRY)


def test_no_hard_coded_composite_in_the_package() -> None:
    """Weights belong in configuration: no registry factor name may appear as a string
    literal anywhere in src/trp/factors source, and no 'weight' literal outside the
    parameter-reading composite module."""
    package_dir = Path(factors_package.__file__).parent
    from trp.factors.compute import registered_transforms

    # A factor whose name doubles as its transform identifier (roic, earnings_stability)
    # legitimately appears once, in its @register_transform string.
    names = {d.name for d in REGISTRY.definitions()} - registered_transforms()
    for path in package_dir.glob("*.py"):
        source = path.read_text("utf-8")
        for name in names:
            assert f'"{name}"' not in source and f"'{name}'" not in source, (
                f"{path.name} hard-codes factor {name!r}; factors live in config"
            )
        if path.name != "composite.py":
            assert '"weight"' not in source, f"{path.name} mentions weights"
    for config_path in Path("config/factors/composites").glob("*.json"):
        body = json.loads(config_path.read_text())
        assert body["transform"] == "composite"
        assert re.fullmatch(r"[a-z0-9_]+", body["name"])
