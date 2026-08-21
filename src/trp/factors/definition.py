"""Versioned factor definitions: configuration, not code (QNT-042).

A factor is a JSON document — name, version, inputs, transform identifier, parameters.
Transforms are named Python implementations registered in ``compute.py``; configuration
holds only their parameters, never expressions (the small-programming-language trap).

In-place edits are detected by a content hash: the definition file declares
``content_hash`` over its own semantic body (name, version, inputs, transform,
parameters — description excluded as cosmetic). A body edited without bumping the
version fails the hash check at load, with the correct hash in the error so an
*intentional* new version is one copy-paste away. Two versions of one factor coexist,
in the registry and in the derived store.
"""

import hashlib
import json
from collections.abc import Mapping
from typing import Any, Self

from pydantic import Field, model_validator

from trp.domain.security import FrozenModel

KNOWN_INPUTS = frozenset({"prices", "corporate_actions", "fundamentals", "universe", "fx"})


class DefinitionError(Exception):
    pass


def compute_content_hash(body: Mapping[str, Any]) -> str:
    """The declared-vs-actual hash: over the semantic fields only, key-sorted JSON."""
    semantic = {
        "name": body["name"],
        "version": body["version"],
        "inputs": sorted(body["inputs"]),
        "transform": body["transform"],
        "parameters": body.get("parameters", {}),
    }
    canonical = json.dumps(semantic, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(canonical.encode()).hexdigest()[:16]


class FactorDefinition(FrozenModel):
    name: str = Field(pattern=r"^[a-z0-9_]+$")
    version: int = Field(ge=1)
    description: str = Field(min_length=1)
    inputs: tuple[str, ...] = Field(min_length=1)
    transform: str = Field(pattern=r"^[a-z0-9_]+$")
    parameters: dict[str, Any] = Field(default_factory=dict)
    content_hash: str

    @model_validator(mode="after")
    def _valid_and_unmutated(self) -> Self:
        unknown = set(self.inputs) - KNOWN_INPUTS
        if unknown:
            raise ValueError(
                f"unknown input dataset(s) {sorted(unknown)}; known: {sorted(KNOWN_INPUTS)}"
            )
        expected = compute_content_hash(self.model_dump())
        if self.content_hash != expected:
            raise ValueError(
                f"{self.name} v{self.version}: content_hash {self.content_hash!r} does not "
                f"match the definition body (expected {expected!r}). A published definition "
                "was edited in place — bump the version and set the new hash instead."
            )
        return self

    def tag(self) -> str:
        return f"{self.name}@v{self.version}"
