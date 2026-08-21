"""Composite factor scoring (QNT-048): configured blends, no hard-coded weights anywhere.

A composite is a factor definition whose transform is ``composite``: components named by
factor name AND version, weights, a per-component direction (+1, or -1 for
lower-is-better metrics like the leverage pair), a REQUIRED standardisation transform
from the QNT-047 registry (weights over raw scales are meaningless), an optional
winsorisation pre-step, and an explicit missing-component policy:

- ``drop``         — a security missing any component gets no composite score.
- ``renormalise``  — remaining weights are rescaled to the original total, subject to
                     ``min_components``; below it, no score.
- ``neutral``      — a missing component contributes a standardised 0. The unsafe one:
                     it awards median rank for a metric the company could not report.
                     Choosing it is visible in the composite's configuration and version.

Every emitted row carries a ``components`` column (``name@version`` joined) so a stored
score identifies exactly the definitions that produced it. Weights exist only in
configuration files — a repository test asserts no composite is hard-coded in
``src/trp/factors``.
"""

from collections.abc import Mapping
from dataclasses import dataclass

import polars as pl

from trp.factors.compute import ComputeContext, compute_factor, register_transform
from trp.factors.definition import DefinitionError, FactorDefinition
from trp.factors.transforms import cross_sectional

MISSING_POLICIES = frozenset({"drop", "renormalise", "neutral"})


@dataclass(frozen=True)
class ComponentSpec:
    name: str
    version: int
    weight: float
    direction: int

    @property
    def label(self) -> str:
        return f"{self.name}@{self.version}"


def component_specs(parameters: Mapping[str, object]) -> list[ComponentSpec]:
    raw = parameters.get("components")
    if not isinstance(raw, list) or not raw:
        raise DefinitionError("composite requires a non-empty components list")
    specs = []
    for entry in raw:
        if not isinstance(entry, Mapping):
            raise DefinitionError(f"component entry {entry!r} is not a mapping")
        specs.append(
            ComponentSpec(
                name=str(entry["name"]),
                version=int(str(entry["version"])),
                weight=float(str(entry["weight"])),
                direction=int(str(entry.get("direction", 1))),
            )
        )
    if any(spec.direction not in (1, -1) for spec in specs):
        raise DefinitionError("component direction must be 1 or -1")
    if sum(abs(spec.weight) for spec in specs) == 0:
        raise DefinitionError("composite weights sum to zero")
    return specs


def validate_composite(definition: FactorDefinition, registry: "object") -> None:
    """Load-time checks: every referenced component version exists; policies are known."""
    parameters = dict(definition.parameters)
    specs = component_specs(parameters)
    for spec in specs:
        try:
            component = registry.get(spec.name, version=spec.version)  # type: ignore[attr-defined]
        except Exception as error:
            raise DefinitionError(
                f"{definition.name}: component {spec.label} is not in the registry ({error})"
            ) from error
        if component.transform == "composite":
            raise DefinitionError(
                f"{definition.name}: nested composites are not supported "
                f"({spec.name} is itself a composite)"
            )
    policy = str(parameters.get("missing_policy", ""))
    if policy not in MISSING_POLICIES:
        raise DefinitionError(
            f"{definition.name}: missing_policy {policy!r} must be one of "
            f"{sorted(MISSING_POLICIES)}"
        )
    cross_sectional(str(parameters.get("standardise", "")))  # raises if unknown


@register_transform("composite")
def _composite(context: ComputeContext, parameters: dict[str, object]) -> pl.DataFrame:
    from trp.factors.registry import FactorRegistry

    registry = FactorRegistry.load()
    specs = component_specs(parameters)
    policy = str(parameters["missing_policy"])
    min_components = int(parameters.get("min_components", len(specs)))  # type: ignore[call-overload]
    standardise = cross_sectional(str(parameters["standardise"]))
    winsorise_params = parameters.get("winsorise")

    component_frames: dict[str, dict[str, float]] = {}
    labels = []
    for spec in specs:
        definition = registry.get(spec.name, version=spec.version)
        frame = compute_factor(definition, context)
        if winsorise_params is not None:
            frame = cross_sectional("winsorise")(frame, winsorise_params)  # type: ignore[arg-type]
        frame = standardise(frame, {})
        labels.append(spec.label)
        component_frames[spec.label] = {
            row["security_id"]: float(row["value"]) * spec.direction
            for row in frame.iter_rows(named=True)
            if row["status"] == "ok" and row["value"] is not None
        }

    components_tag = ";".join(labels)
    rows = []
    for security_id in context.security_ids:
        sid = str(security_id)
        present: list[tuple[float, float]] = []  # (weight, standardised value)
        missing: list[str] = []
        for spec, label in zip(specs, labels, strict=True):
            value = component_frames[label].get(sid)
            if value is None:
                missing.append(label)
            else:
                present.append((spec.weight, value))
        if missing and policy == "drop":
            rows.append(_row(sid, "no_data", None, [f"missing {';'.join(missing)}"]))
            continue
        if policy == "neutral":
            weight_of = {spec.label: spec.weight for spec in specs}
            present = present + [(weight_of[m], 0.0) for m in missing]
            missing_note = [f"neutral for {';'.join(missing)}"] if missing else []
        else:
            missing_note = [f"renormalised over {len(present)}"] if missing else []
        if len(present) < min_components:
            note = f"{len(present)} < {min_components} components"
            rows.append(_row(sid, "insufficient_data", None, [note]))
            continue
        total_weight = sum(abs(w) for w, _v in present)
        if total_weight == 0:
            rows.append(_row(sid, "not_meaningful", None, ["zero total weight"]))
            continue
        score = sum(w * v for w, v in present) / total_weight
        rows.append(_row(sid, "ok", score, missing_note))
    frame = pl.DataFrame(
        rows,
        schema={
            "security_id": pl.Utf8,
            "status": pl.Utf8,
            "value": pl.Float64,
            "warnings": pl.List(pl.Utf8),
        },
    )
    return frame.with_columns(pl.lit(components_tag).alias("components"))


def _row(sid: str, status: str, value: float | None, warnings: list[str]) -> dict:  # type: ignore[type-arg]
    return {"security_id": sid, "status": status, "value": value, "warnings": warnings}
