"""Provider items → canonical line items, with everything unmapped surfaced, never guessed.

The whole design turns on one asymmetry: a *missing* canonical value is an inconvenience a
researcher can see and work around, whereas a *wrongly mapped* one is a plausible number
that passes every type check and quietly corrupts a factor. So this module never coerces.
An item with no mapping entry keeps its raw provider name and value and comes back in
``unmapped``; it is counted in a summary the caller can log or assert on; it never appears
under a canonical name.

What normalisation does, exhaustively: look up ``(statement, provider_item)`` in the
provider's mapping table, apply the entry's explicit sign flag, and attach the canonical
item's unit kind. What it does not do: compute ``available_at`` (QNT-020's field, set by
whoever knows the filing timeline), decide whether a value is an original or a restatement
(QNT-022), convert currency (QNT-023, at query time), rescale magnitudes, or invent a
timestamp of any kind — nothing here reads the clock, so normalising the same payload in
January and in June produces identical output.

Determinism is a stated guarantee, not an accident: output is sorted by
``(statement, line item, provider item)``, so it never depends on dict iteration order, and
re-normalising the same payload serialises byte-identically. Every result records the
taxonomy version and mapping version that produced it, so a canonical row traces back to
raw payload plus mapping version and a later mapping correction is distinguishable from a
provider data change (QUANT_PRINCIPLES §4).
"""

from collections.abc import Iterable
from datetime import date, datetime
from decimal import Decimal
from enum import StrEnum

from pydantic import Field

from trp.canonical.fundamentals.taxonomy import (
    LineItemTaxonomy,
    MappingEntry,
    MappingTable,
    ReviewStatus,
    Sign,
    SignConvention,
    UnitKind,
    default_mapping_table,
    default_taxonomy,
)
from trp.domain.fundamentals import FundamentalValue, PeriodType, StatementType
from trp.domain.identifiers import SecurityId
from trp.domain.security import FrozenModel


class NormalisationError(Exception):
    pass


class DuplicateProviderItemError(NormalisationError):
    """The same ``(statement, provider_item)`` twice in one payload.

    Not resolvable by taking either one: a payload that reports revenue twice is either
    two periods conflated or a parser bug, and both need a human.
    """

    def __init__(self, duplicates: list[tuple[StatementType, str]]) -> None:
        self.duplicates = duplicates
        super().__init__(
            f"payload repeats {[(s.value, n) for s, n in duplicates]}: one item per "
            "statement per payload — silently keeping one of them would hide the conflict"
        )


class ProviderMismatchError(NormalisationError):
    pass


class ProviderLineItem(FrozenModel):
    """One item as the provider stated it: a statement, a raw name, and a value.

    Deliberately has no timestamp field. Period and availability belong to the payload's
    envelope, not to the line, and normalisation has no business touching either.

    A provider null is an absent fact, not a fact worth normalising: adapters drop nulls
    before they get here rather than propagating a value that means "we do not know".
    """

    statement: StatementType
    name: str = Field(min_length=1, description="raw provider name, verbatim")
    value: Decimal = Field(strict=True, description="strict: float input is rejected (DEC-005)")

    @property
    def key(self) -> tuple[StatementType, str]:
        return (self.statement, self.name)


class UnmappedReason(StrEnum):
    """Why an item did not become canonical — the difference between a known gap and an
    unknown one, which decides whether it needs a human or is already settled."""

    NO_MAPPING = "no_mapping"
    DELIBERATELY_EXCLUDED = "deliberately_excluded"


class UnmappedLineItem(FrozenModel):
    """A preserved provider item: raw name, raw value, and why it stayed raw."""

    statement: StatementType
    provider_item: str
    value: Decimal
    reason: UnmappedReason
    note: str = ""


class NormalisedLineItem(FrozenModel):
    """A mapped item, carrying the provenance needed to audit the mapping that made it.

    ``value`` has the entry's sign flag applied and nothing else done to it: same
    magnitude, same currency, same scale as the provider stated.
    """

    statement: StatementType
    line_item: str
    value: Decimal
    unit_kind: UnitKind
    sign_convention: SignConvention
    provider: str
    provider_item: str
    sign_applied: Sign
    review_status: ReviewStatus
    taxonomy_version: str
    mapping_version: str

    @property
    def sort_key(self) -> tuple[str, str, str]:
        return (self.statement.value, self.line_item, self.provider_item)


class NormalisationSummary(FrozenModel):
    """Counts a caller can log or assert on — the point being that unmapped items are
    *counted*, so silent loss is impossible to mistake for a clean run."""

    items_in: int
    mapped: int
    unmapped_no_mapping: int
    deliberately_excluded: int
    mapped_verified: int
    mapped_provisional: int


class NormalisationResult(FrozenModel):
    """Everything the payload became: canonical items, preserved raw items, versions."""

    provider: str
    taxonomy_version: str
    mapping_version: str
    mapped: tuple[NormalisedLineItem, ...] = ()
    unmapped: tuple[UnmappedLineItem, ...] = ()

    @property
    def summary(self) -> NormalisationSummary:
        return NormalisationSummary(
            items_in=len(self.mapped) + len(self.unmapped),
            mapped=len(self.mapped),
            unmapped_no_mapping=sum(
                1 for u in self.unmapped if u.reason is UnmappedReason.NO_MAPPING
            ),
            deliberately_excluded=sum(
                1 for u in self.unmapped if u.reason is UnmappedReason.DELIBERATELY_EXCLUDED
            ),
            mapped_verified=sum(1 for m in self.mapped if m.review_status is ReviewStatus.VERIFIED),
            mapped_provisional=sum(
                1 for m in self.mapped if m.review_status is ReviewStatus.PROVISIONAL
            ),
        )

    def item(self, line_item: str) -> NormalisedLineItem | None:
        """The mapped item under this canonical name, or ``None``."""
        return next((m for m in self.mapped if m.line_item == line_item), None)


def _signed(value: Decimal, sign: Sign) -> Decimal:
    """Apply the mapping entry's sign flag. Exact — a negation, never a rescale."""
    return value if sign is Sign.AS_REPORTED else -value


def _mapped_item(
    item: ProviderLineItem,
    entry: MappingEntry,
    taxonomy: LineItemTaxonomy,
    table: MappingTable,
) -> NormalisedLineItem:
    assert entry.canonical is not None  # callers filter on this; the loader guarantees it exists
    canonical = taxonomy.item(entry.canonical)
    return NormalisedLineItem(
        statement=canonical.statement,
        line_item=canonical.name,
        value=_signed(item.value, entry.sign),
        unit_kind=canonical.unit_kind,
        sign_convention=canonical.sign_convention,
        provider=table.provider,
        provider_item=item.name,
        sign_applied=entry.sign,
        review_status=entry.review_status,
        taxonomy_version=taxonomy.version,
        mapping_version=table.version,
    )


def normalise_line_items(
    items: Iterable[ProviderLineItem],
    *,
    provider: str,
    mappings: MappingTable | None = None,
    taxonomy: LineItemTaxonomy | None = None,
) -> NormalisationResult:
    """Map one payload's items to canonical line items, preserving everything unmapped.

    ``provider`` selects the packaged mapping table unless ``mappings`` is passed
    explicitly (tests, and a bake-off comparing candidate tables). Passing a table whose
    provider disagrees raises rather than quietly using it, because the provider name is
    what the output claims the numbers came from.

    Returns a :class:`NormalisationResult` whose ``mapped`` items are ready to become
    :class:`~trp.domain.fundamentals.FundamentalValue` records once the caller supplies
    the period and availability facts (see :func:`to_fundamental_value`), and whose
    ``unmapped`` items carry raw provider names and untouched values.
    """
    table = mappings if mappings is not None else default_mapping_table(provider)
    if table.provider != provider:
        raise ProviderMismatchError(
            f"mapping table is for {table.provider!r}, not {provider!r}: the provider name "
            "is recorded on every canonical row and must be the one that produced it"
        )
    resolved_taxonomy = taxonomy if taxonomy is not None else default_taxonomy()

    payload = list(items)
    seen: set[tuple[StatementType, str]] = set()
    duplicates: list[tuple[StatementType, str]] = []
    for item in payload:
        if item.key in seen:
            duplicates.append(item.key)
        seen.add(item.key)
    if duplicates:
        raise DuplicateProviderItemError(sorted(duplicates, key=lambda k: (k[0].value, k[1])))

    mapped: list[NormalisedLineItem] = []
    unmapped: list[UnmappedLineItem] = []
    for item in payload:
        entry = table.entry(item.statement, item.name)
        if entry is None:
            unmapped.append(
                UnmappedLineItem(
                    statement=item.statement,
                    provider_item=item.name,
                    value=item.value,
                    reason=UnmappedReason.NO_MAPPING,
                    note="no mapping entry; add one deliberately or leave it unmapped",
                )
            )
        elif entry.canonical is None:
            unmapped.append(
                UnmappedLineItem(
                    statement=item.statement,
                    provider_item=item.name,
                    value=item.value,
                    reason=UnmappedReason.DELIBERATELY_EXCLUDED,
                    note=entry.note,
                )
            )
        else:
            mapped.append(_mapped_item(item, entry, resolved_taxonomy, table))

    return NormalisationResult(
        provider=table.provider,
        taxonomy_version=resolved_taxonomy.version,
        mapping_version=table.version,
        mapped=tuple(sorted(mapped, key=lambda m: m.sort_key)),
        unmapped=tuple(sorted(unmapped, key=lambda u: (u.statement.value, u.provider_item))),
    )


def sign_violations(result: NormalisationResult) -> tuple[NormalisedLineItem, ...]:
    """Mapped items whose sign contradicts the taxonomy's stated convention.

    Not raised on, because a genuine outlier exists (a company with a positive net
    buyback line in a placing year) and refusing the row would lose it. This is the hook
    for a validation report: a mapping whose sign flag is wrong shows up here as data,
    across many securities at once, rather than as one odd-looking factor value. Zero
    never violates anything.
    """
    violations: list[NormalisedLineItem] = []
    for item in result.mapped:
        if item.value == 0:
            continue
        wrong_way = (item.sign_convention is SignConvention.POSITIVE and item.value < 0) or (
            item.sign_convention is SignConvention.NEGATIVE and item.value > 0
        )
        if wrong_way:
            violations.append(item)
    return tuple(violations)


def to_fundamental_value(
    item: NormalisedLineItem,
    *,
    security_id: SecurityId,
    period_end: date,
    period_type: PeriodType,
    currency: str,
    available_at: datetime,
    source: str,
    filed_at: datetime | None = None,
    availability_imputed: bool = False,
    imputation_rule: str | None = None,
) -> FundamentalValue:
    """Build the QNT-020 record from a mapped item plus the facts only the caller knows.

    ``available_at`` is required from the caller and never derived here: normalisation
    knows nothing about announcement timelines, and DEC-007's conservative imputation is
    ingestion's decision, made where the per-market lag table lives.

    ``currency`` is the reporting currency as filed and is stored unconverted — QNT-023
    converts at query time and nowhere else.
    """
    return FundamentalValue(
        security_id=security_id,
        statement=item.statement,
        line_item=item.line_item,
        period_end=period_end,
        period_type=period_type,
        currency=currency,
        value=item.value,
        filed_at=filed_at,
        available_at=available_at,
        source=source,
        availability_imputed=availability_imputed,
        imputation_rule=imputation_rule,
    )
