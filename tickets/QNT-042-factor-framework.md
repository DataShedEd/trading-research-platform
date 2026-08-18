# QNT-042 — Versioned factor definition framework

- **Ticket ID:** QNT-042
- **Status:** DONE
- **Priority:** P2
- **Epic:** EPIC 7 — Factor Engine

## Problem
Factors written as hard-coded functions cannot be reproduced after they change. A momentum
definition edited in place invalidates every stored value computed under the old rule, with nothing
recording which rule produced which number, and a composite score baked into code makes the
weighting a permanent assumption rather than an experimental variable.

## Objective
Define factors as versioned configuration — name, version, inputs, transform, parameters — held in a
registry, with every computed value tagged with the definition version and the versions of the data
it consumed.

## Scope
`src/trp/factors/` package: `definition.py` (the `FactorDefinition` model and its parameter schema),
`registry.py` (load definitions from configuration files, look up by name and version, reject
duplicate or mutated versions), `compute.py` (the execution surface that resolves inputs, applies
the transform, and writes tagged values to `data/derived/factors/`), plus the definition files
themselves under `config/factors/`.

## Out of scope
Concrete factor definitions (QNT-044, QNT-045, QNT-046); cross-sectional transforms (QNT-047);
composites (QNT-048); the point-in-time acceptance suite (QNT-049).

## Acceptance criteria
- [x] A factor is defined entirely in configuration — name, version, input datasets, transform
      identifier, parameters — and loading the registry validates each definition against a schema
      with typed errors on failure.
- [x] Every computed factor value is persisted with its definition name, definition version, and
      the versions of its input datasets; a value with no version tag cannot be written.
- [x] Editing a published definition without incrementing its version is detected and rejected — a
      test mutates a definition file and asserts the registry raises.
- [x] Computing the same factor twice over unchanged inputs produces identical values
      (deterministic), and two versions of the same factor can coexist in the derived store.
- [x] Transforms are registered by identifier rather than imported ad hoc, so the set of available
      transforms is enumerable and a definition naming an unknown transform fails at load time.

## Technical notes
Version detection can be a content hash of the definition recorded alongside the declared version;
a mismatch between hash and version is the signal that a definition was edited in place. Store
values in `data/derived/factors/` as Parquet partitioned by factor name and version.

Factor computation reads through the point-in-time APIs only, so `as_of` is a first-class argument
of the compute surface rather than a detail of individual factors — this is what makes QNT-049
possible.

## Dependencies
QNT-025 — supplies the point-in-time fundamentals access that factor inputs are resolved through.
QNT-038 — supplies the universe query determining which securities a factor is computed for.

## Risks
An over-general configuration language becomes a small programming language with no debugger.
Mitigated by keeping transforms as named Python implementations and configuration to their
parameters, rather than allowing arbitrary expressions.

## Testing requirements
`tests/factors/test_definition.py`, `tests/factors/test_registry.py`, `tests/factors/test_compute.py`
— schema validation, unknown-transform rejection, in-place-edit detection, determinism, coexisting
versions, and version tagging of written values.

`tests/timetravel/test_factor_framework.py` (marker `timetravel`) — the compute surface must
propagate `as_of` to every input read; a test asserts that data with `available_at` after `as_of`
is not visible to a factor computation.

## Documentation requirements
`docs/DATA_MODEL.md` derived-factors section updated with the definition and version-tagging
contract. A short authoring guide for adding a factor definition, and a `DECISIONS.md` entry for
the configuration format.

## Completion notes
2026-08-18. `src/trp/factors/{definition,registry,compute}.py` + `config/factors/README.md`
(authoring guide) + DEC-015. Definitions are JSON with a declared content hash over the
semantic body (description excluded as cosmetic — tested); an in-place edit fails at load
with the expected hash in the error. Registry rejects duplicate versions and unknown
transforms at load (validated against the enumerable transform registry). Compute surface:
`ComputeContext` carries inputs + `as_of`; transforms are registered by identifier; the
first registered transform is `window_total_return` over the QNT-043 returns engine (the
momentum primitive QNT-044 will parameterise). Values are tagged
factor/version/end/as_of/input-versions; the writer refuses untagged frames, refuses
overwrites, and versions coexist (tested). Determinism tested. Timetravel test proves the
surface propagates `as_of` (a September-published dividend invisible to an August
computation). Deviation: definitions currently live only in tests — the shipped
`config/factors/` holds the README; QNT-044 lands the real definitions. Tests:
`tests/factors/test_framework.py` (12). Suite green.
