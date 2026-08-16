"""The canonical line-item taxonomy and provider→canonical mapping tables, as data.

Two versioned data assets live behind this module and neither is Python:

* ``line_item_taxonomy.json`` — the canonical contract: every line item's statement
  membership, unit kind, sign convention and one-line definition;
* ``mappings/<provider>.json`` — one table per provider, each entry naming a provider item,
  the canonical item it becomes, an explicit sign flag and a review status.

Keeping them as files means a mapping is reviewable in a diff, editable without a code
change, and comparable across providers for the Epic 5 bake-off. Validation lives here, in
the loader, not in the file format: a mapping naming a canonical item that does not exist,
naming a canonical item on the wrong statement, repeating a provider key, or written
against a different taxonomy version is rejected at load time rather than producing
plausible wrong rows later.

The mapping key is ``(statement, provider_item)``, not the provider item alone: providers
routinely use one name on two statements (``netIncome`` heads the income statement and
opens the cash flow statement), and collapsing them would silently merge two facts.

Three things this module deliberately does not do: it never guesses (an unmapped item stays
unmapped — see :mod:`trp.canonical.fundamentals.normalisation`), it never converts currency
(QNT-023 does that at query time), and it never rescales magnitudes. A provider reporting
in thousands is a real problem, but it is one that must be seen in a recorded payload
before it is modelled; a scale factor invented now would be applied on faith.
"""

import json
from collections.abc import Iterator, Mapping
from enum import StrEnum
from functools import cache
from importlib.resources import files
from pathlib import Path
from typing import Self

from pydantic import Field, model_validator

from trp.domain.fundamentals import StatementType
from trp.domain.security import FrozenModel

_PACKAGE = "trp.canonical.fundamentals"
_TAXONOMY_FILE = "line_item_taxonomy.json"
_MAPPINGS_DIR = "mappings"


class TaxonomyError(Exception):
    """Base for taxonomy and mapping-table failures — all of them loud, none recoverable
    by falling back to a default: a bad mapping table has no safe interpretation."""


class UnknownCanonicalItemError(TaxonomyError):
    def __init__(self, name: str, known: tuple[str, ...]) -> None:
        self.name = name
        super().__init__(
            f"{name!r} is not a canonical line item in taxonomy (known: {list(known)}). "
            "Add it to line_item_taxonomy.json with a definition and sign convention, and "
            "bump the taxonomy version — never map to a name that does not exist."
        )


class MappingTableError(TaxonomyError):
    """A provider mapping file that cannot be trusted: duplicate keys, unknown canonical
    names, statement disagreement, or a taxonomy version it was not written against."""


class UnknownProviderError(TaxonomyError):
    def __init__(self, provider: str, known: tuple[str, ...]) -> None:
        self.provider = provider
        super().__init__(f"no mapping table for provider {provider!r} (known: {list(known)})")


class UnitKind(StrEnum):
    """What a value *is*, which decides what may be done to it.

    Load-bearing beyond documentation: QNT-023 converts ``CURRENCY_AMOUNT`` and
    ``PER_SHARE_AMOUNT`` by an FX rate and must never touch a ``SHARE_COUNT`` or a
    ``RATIO`` — FX-converting a share count is precisely the plausible-looking wrong
    number this platform is built to prevent.
    """

    CURRENCY_AMOUNT = "currency_amount"
    PER_SHARE_AMOUNT = "per_share_amount"
    SHARE_COUNT = "share_count"
    RATIO = "ratio"

    @property
    def is_monetary(self) -> bool:
        return self in (UnitKind.CURRENCY_AMOUNT, UnitKind.PER_SHARE_AMOUNT)


class SignConvention(StrEnum):
    """The canonical sign a line item carries. See the taxonomy file's notes."""

    POSITIVE = "positive"
    NEGATIVE = "negative"
    EITHER = "either"


class Sign(StrEnum):
    """What the mapping must do to the provider's sign to reach the canonical one.

    An explicit flag on the mapping *entry* rather than a branch in transform code, so a
    provider that reports capital expenditure as a positive magnitude is visibly corrected
    in a reviewable data file, and a wrong correction is visible as data.
    """

    AS_REPORTED = "as_reported"
    FLIP = "flip"


class ReviewStatus(StrEnum):
    """How much a mapping entry has been checked. Never decorative: an entry that is
    ``PROVISIONAL`` has been read off provider documentation but not confirmed against a
    recorded payload, and a factor built on one is a factor with an open question."""

    VERIFIED = "verified"
    PROVISIONAL = "provisional"
    EXCLUDED = "excluded"


class LineItem(FrozenModel):
    """One canonical line item: the contract research code writes against."""

    name: str = Field(pattern=r"^[a-z][a-z0-9_]*$", description="canonical snake_case name")
    statement: StatementType
    unit_kind: UnitKind
    sign_convention: SignConvention
    definition: str = Field(min_length=10, description="one line; the contract, not a label")


class LineItemTaxonomy(FrozenModel):
    """The loaded taxonomy file, with its version.

    The version is recorded on every normalisation output, so a canonical row can be traced
    to the taxonomy that produced it and a taxonomy change is distinguishable from a
    provider data change on re-derivation (QUANT_PRINCIPLES §4).
    """

    version: str = Field(pattern=r"^\d+\.\d+$")
    notes: str = ""
    items: tuple[LineItem, ...] = Field(min_length=1)

    @model_validator(mode="after")
    def _names_are_unique(self) -> Self:
        names = [item.name for item in self.items]
        duplicated = sorted({name for name in names if names.count(name) > 1})
        if duplicated:
            raise ValueError(f"duplicate canonical line items: {duplicated}")
        return self

    @property
    def names(self) -> tuple[str, ...]:
        return tuple(item.name for item in self.items)

    def item(self, name: str) -> LineItem:
        """The canonical item, or :class:`UnknownCanonicalItemError` — never a guess."""
        for item in self.items:
            if item.name == name:
                return item
        raise UnknownCanonicalItemError(name, self.names)

    def get(self, name: str) -> LineItem | None:
        """The canonical item, or ``None`` where a caller legitimately tolerates absence
        (a stored line item predating the taxonomy, say). Prefer :meth:`item`."""
        return next((item for item in self.items if item.name == name), None)

    def for_statement(self, statement: StatementType) -> tuple[LineItem, ...]:
        return tuple(item for item in self.items if item.statement == statement)


class MappingEntry(FrozenModel):
    """One provider item's fate: a canonical name, or an explicit refusal to map.

    ``canonical is None`` with ``review_status=EXCLUDED`` is a *deliberate* non-mapping —
    a provider aggregate we have looked at and refuse to map. It reads out of
    normalisation as unmapped-by-decision, distinguishable from never-considered, which is
    the difference between a known gap and an unknown one.
    """

    provider_item: str = Field(min_length=1, description="raw name, verbatim from the payload")
    statement: StatementType
    canonical: str | None = Field(default=None, pattern=r"^[a-z][a-z0-9_]*$")
    sign: Sign = Sign.AS_REPORTED
    review_status: ReviewStatus = ReviewStatus.PROVISIONAL
    note: str = ""

    @model_validator(mode="after")
    def _exclusion_is_explicit(self) -> Self:
        if (self.canonical is None) != (self.review_status is ReviewStatus.EXCLUDED):
            raise ValueError(
                f"{self.provider_item!r}: canonical=null and review_status='excluded' must be "
                "used together — an entry either maps somewhere or explicitly refuses to"
            )
        if self.canonical is None and self.sign is not Sign.AS_REPORTED:
            raise ValueError(f"{self.provider_item!r}: an excluded entry cannot flip a sign")
        return self

    @property
    def key(self) -> tuple[StatementType, str]:
        return (self.statement, self.provider_item)


class MappingTable(FrozenModel):
    """One provider's mapping file, validated against the taxonomy at load time."""

    provider: str = Field(pattern=r"^[a-z][a-z0-9_]*$")
    version: str = Field(pattern=r"^\d+\.\d+$")
    taxonomy_version: str = Field(
        pattern=r"^\d+\.\d+$", description="the taxonomy version this table was written against"
    )
    notes: str = ""
    entries: tuple[MappingEntry, ...] = Field(min_length=1)

    @model_validator(mode="after")
    def _keys_and_targets_are_unique(self) -> Self:
        keys = [entry.key for entry in self.entries]
        duplicated = sorted({key for key in keys if keys.count(key) > 1})
        if duplicated:
            raise ValueError(
                f"duplicate provider keys {duplicated}: one provider item on one statement "
                "cannot map two ways — the second would silently win"
            )
        targets = [e.canonical for e in self.entries if e.canonical is not None]
        contested = sorted({name for name in targets if targets.count(name) > 1})
        if contested:
            raise ValueError(
                f"canonical items {contested} are each claimed by two provider items: a "
                "payload carrying both would yield two rows for one fact. A provider that "
                "renamed a field needs a second, versioned mapping table, not two entries"
            )
        return self

    def entry(self, statement: StatementType, provider_item: str) -> MappingEntry | None:
        """The entry for this key, or ``None`` for an item nobody has mapped."""
        key = (statement, provider_item)
        return next((e for e in self.entries if e.key == key), None)

    @property
    def mapped_entries(self) -> tuple[MappingEntry, ...]:
        return tuple(e for e in self.entries if e.canonical is not None)


def _validate_against_taxonomy(table: MappingTable, taxonomy: LineItemTaxonomy) -> None:
    """Cross-file invariants: version agreement, canonical existence, statement agreement.

    Kept out of the Pydantic models because it needs both files; kept in the *loader* so
    there is no way to obtain a ``MappingTable`` that has not been checked against the
    taxonomy it claims.
    """
    if table.taxonomy_version != taxonomy.version:
        raise MappingTableError(
            f"provider {table.provider!r} mapping v{table.version} was written against "
            f"taxonomy v{table.taxonomy_version}, but the loaded taxonomy is "
            f"v{taxonomy.version}: review the mapping against the changed definitions and "
            "update taxonomy_version deliberately"
        )
    for entry in table.mapped_entries:
        assert entry.canonical is not None  # mapped_entries filters on exactly this
        try:
            item = taxonomy.item(entry.canonical)
        except UnknownCanonicalItemError as exc:
            raise MappingTableError(f"provider {table.provider!r}: {exc}") from exc
        if item.statement != entry.statement:
            raise MappingTableError(
                f"provider {table.provider!r}: {entry.provider_item!r} is mapped to "
                f"{entry.canonical!r} under statement {entry.statement.value!r}, but the "
                f"taxonomy places {entry.canonical!r} on {item.statement.value!r}"
            )


def load_taxonomy(path: Path | None = None) -> LineItemTaxonomy:
    """Load and fully validate the taxonomy — the packaged file, or an override path."""
    if path is None:
        payload = (files(_PACKAGE) / _TAXONOMY_FILE).read_text("utf-8")
    else:
        payload = path.read_text("utf-8")
    return LineItemTaxonomy.model_validate_json(payload)


@cache
def default_taxonomy() -> LineItemTaxonomy:
    """The packaged taxonomy, parsed once — versioned repository content, not a lookup."""
    return load_taxonomy()


def _mappings_directory(directory: Path | None) -> Path:
    if directory is not None:
        return directory
    resource = files(_PACKAGE) / _MAPPINGS_DIR
    return Path(str(resource))


def available_providers(directory: Path | None = None) -> tuple[str, ...]:
    """Providers with a shipped mapping table, sorted — deterministic, not filesystem order."""
    return tuple(sorted(p.stem for p in _mappings_directory(directory).glob("*.json")))


def load_mapping_table(
    provider: str,
    *,
    directory: Path | None = None,
    taxonomy: LineItemTaxonomy | None = None,
) -> MappingTable:
    """Load one provider's mapping table and validate it against the taxonomy.

    Raises :class:`UnknownProviderError` for a provider with no table and
    :class:`MappingTableError` for a table that is malformed, self-inconsistent, or
    inconsistent with the taxonomy. There is no lenient mode: a mapping table that half
    loads produces canonical rows nobody can trust.
    """
    root = _mappings_directory(directory)
    path = root / f"{provider}.json"
    if not path.is_file():
        raise UnknownProviderError(provider, available_providers(directory))

    try:
        table = MappingTable.model_validate_json(path.read_text("utf-8"))
    except (ValueError, json.JSONDecodeError) as exc:
        raise MappingTableError(f"{path.name} is not a valid mapping table: {exc}") from exc
    if table.provider != provider:
        raise MappingTableError(
            f"{path.name} declares provider {table.provider!r}: the file name is the key"
        )
    _validate_against_taxonomy(table, taxonomy if taxonomy is not None else default_taxonomy())
    return table


@cache
def default_mapping_table(provider: str) -> MappingTable:
    """A packaged provider mapping table, parsed and validated once."""
    return load_mapping_table(provider)


def load_all_mapping_tables(
    directory: Path | None = None, *, taxonomy: LineItemTaxonomy | None = None
) -> Mapping[str, MappingTable]:
    """Every shipped table, validated. Used by tests and by bake-off coverage comparison."""
    return {
        provider: load_mapping_table(provider, directory=directory, taxonomy=taxonomy)
        for provider in available_providers(directory)
    }


def iter_line_items(taxonomy: LineItemTaxonomy | None = None) -> Iterator[LineItem]:
    """The taxonomy's items in file order — stable across runs, so output is comparable."""
    return iter((taxonomy if taxonomy is not None else default_taxonomy()).items)
