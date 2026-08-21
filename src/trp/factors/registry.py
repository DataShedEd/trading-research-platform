"""The factor registry: definitions loaded from ``config/factors/*.json``.

Duplicate (name, version) pairs are rejected; unknown transform identifiers are rejected
at load time against the enumerable transform registry (``compute.registered_transforms``)
so a typo fails immediately, not at first computation.
"""

import json
from collections import defaultdict
from pathlib import Path
from typing import Self

from pydantic import ValidationError

from trp.factors.definition import DefinitionError, FactorDefinition

DEFAULT_CONFIG_DIR = Path("config") / "factors"


class FactorRegistry:
    def __init__(self, definitions: list[FactorDefinition]) -> None:
        self._by_name: dict[str, dict[int, FactorDefinition]] = defaultdict(dict)
        for definition in definitions:
            versions = self._by_name[definition.name]
            if definition.version in versions:
                raise DefinitionError(
                    f"duplicate definition {definition.tag()} — versions are immutable"
                )
            versions[definition.version] = definition

    @classmethod
    def load(
        cls, directory: Path = DEFAULT_CONFIG_DIR, *, known_transforms: frozenset[str] | None = None
    ) -> Self:
        if known_transforms is None:
            import trp.factors.composite
            import trp.factors.fundamental  # noqa: F401 - registers its transforms
            from trp.factors.compute import registered_transforms

            known_transforms = registered_transforms()
        definitions: list[FactorDefinition] = []
        for path in sorted(directory.rglob("*.json")):
            try:
                definition = FactorDefinition.model_validate(json.loads(path.read_text()))
            except (json.JSONDecodeError, ValidationError) as exc:
                raise DefinitionError(f"{path.name}: {exc}") from exc
            if definition.transform not in known_transforms:
                raise DefinitionError(
                    f"{path.name}: unknown transform {definition.transform!r}; "
                    f"registered: {sorted(known_transforms)}"
                )
            definitions.append(definition)
        registry = cls(definitions)
        from trp.factors.composite import validate_composite

        for definition in definitions:
            if definition.transform == "composite":
                validate_composite(definition, registry)
        return registry

    def get(self, name: str, version: int | None = None) -> FactorDefinition:
        versions = self._by_name.get(name)
        if not versions:
            raise DefinitionError(f"no factor named {name!r}; known: {sorted(self._by_name)}")
        if version is None:
            return versions[max(versions)]
        if version not in versions:
            raise DefinitionError(f"{name} has no version {version}; available: {sorted(versions)}")
        return versions[version]

    def definitions(self) -> tuple[FactorDefinition, ...]:
        return tuple(
            self._by_name[name][version]
            for name in sorted(self._by_name)
            for version in sorted(self._by_name[name])
        )
