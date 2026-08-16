# QNT-021 — Financial statement normalisation model

- **Ticket ID:** QNT-021
- **Status:** BACKLOG
- **Priority:** P1
- **Epic:** EPIC 4 — Fundamental Data

## Problem
Every provider names financial statement lines differently — `totalRevenue`, `revenue`,
`Revenues`, `turnover` — and each uses a slightly different definition and sign convention. If
research code queries provider-specific names, factor definitions become provider-specific, the
bake-off cannot compare like with like, and switching provider invalidates every stored result.
The opposite failure is just as bad: mapping aggressively so that everything lands in a canonical
bucket produces silently wrong values, because the item that looked like operating cash flow was
something else.

## Objective
Define a canonical line-item taxonomy covering income statement, balance sheet and cash flow
statement, express provider-to-canonical mappings as versioned data rather than code, and specify
a strict policy for unmapped items: preserve the raw name, flag it, never coerce.

## Scope
`src/trp/canonical/fundamentals/taxonomy.py` (canonical line-item enumeration or registry with
statement membership, units, sign convention and definition text); mapping tables as data files
under `src/trp/canonical/fundamentals/mappings/<provider>.<ext>` with a loader and schema
validation; a `normalise_line_items` function taking a provider payload's items plus a provider
identifier and returning canonical `FundamentalValue` inputs alongside an explicit collection of
unmapped items; unit tests.

## Out of scope
The domain record itself (QNT-020); revisions (QNT-022); currency (QNT-023); storage (QNT-024);
querying (QNT-025); real provider payload shapes — this ticket works from stub/recorded fixtures,
and provider adapters (QNT-031…033) supply real ones later. Derived ratios and factor definitions
are Epic 8 and are explicitly not part of the taxonomy.

## Acceptance criteria
- [ ] A canonical taxonomy exists covering, at minimum, the line items needed for value and
      quality factors across all three statements, each entry carrying statement membership, a
      one-line definition, a unit kind (currency amount | share count | ratio) and a documented
      sign convention.
- [ ] Provider mappings live in data files, not Python `if`/`dict` literals embedded in transform
      code; each mapping entry records provider item name, canonical item, and a mapping-confidence
      or review status; the loader validates every file against a schema at load time and fails
      loudly on an unknown canonical name or duplicate provider key.
- [ ] Normalising the same fixture payload twice produces byte-identical canonical output
      (deterministic ordering, no dependence on dict iteration or wall-clock time).
- [ ] An item with no mapping is never dropped and never guessed: it is returned in an explicit
      unmapped collection carrying the raw provider name and value, is counted in a summary that
      the caller can log or assert on, and does not appear under a canonical name.
- [ ] Mapping tables are versioned — the taxonomy and each mapping file carry a version identifier
      that is recorded on normalisation output, so a canonical row can be traced to the mapping
      version that produced it.
- [ ] Unit tests cover a full fixture payload mapping deterministically, an unmapped item being
      surfaced rather than coerced, a duplicate/conflicting mapping being rejected at load, and a
      sign-convention case (e.g. capital expenditure) normalising to the documented sign.

## Technical notes
The taxonomy is a contract, so keep it small and defensible rather than exhaustive: it is far
better to have forty items with precise definitions and honest unmapped counts than three hundred
half-understood ones. Add items when a factor needs them.

Mappings as data (per `docs/ARCHITECTURE.md`'s preference for simple, inspectable components) means
they can be reviewed in a diff, edited without a code change, and — importantly for Epic 5 —
compared across providers. Prefer a plain declarative format that a human can read in review; the
loader, not the file format, is where validation happens.

Sign conventions are the classic silent-error source: providers disagree on whether capital
expenditure, dividends paid, and share buybacks are negative or positive. The canonical convention
must be stated once in the taxonomy entry and applied in the mapping (as an explicit sign flag on
the mapping entry, not as ad-hoc code), so that a wrong sign is visible as data.

Normalisation output feeds `FundamentalValue` construction from QNT-020, so it must not itself
compute `available_at`; it maps names, units and signs only. Nothing here converts currency —
values stay in the reporting currency per QNT-023 — and nothing here decides whether a value is an
original or a restatement, which is QNT-022's job.

Record the mapping version on output so that a later mapping correction is distinguishable from a
provider data change when re-derivation happens. This matters for reproducibility
(QUANT_PRINCIPLES §4): a canonical row must be traceable to raw payload plus mapping version.

## Dependencies
QNT-020 — the `FundamentalValue` record whose `line_item` field this taxonomy populates.

## Risks
An over-eager mapping produces plausible but wrong canonical values that no test catches because
the number looks reasonable — the most dangerous failure mode in the data layer. Mitigated by the
never-coerce policy, mapping-confidence metadata, and asserting unmapped counts in tests rather
than tolerating silent loss. A second risk is taxonomy churn breaking stored derived data;
mitigated by versioning the taxonomy and recording the version on every row.

## Testing requirements
`tests/canonical/test_fundamental_taxonomy.py` and
`tests/canonical/test_provider_mapping.py`, working from a checked-in fixture payload that
deliberately contains several mappable items, one unmapped item, one item with an inverted provider
sign, and one duplicate. Determinism test: normalise twice, compare exactly. Loader tests for
schema violations. No `timetravel` marker is required — this ticket reads no historical store and
exposes no as-of API — but tests must assert that normalisation never invents or alters a
timestamp.

## Documentation requirements
`docs/DATA_MODEL.md` gains a short subsection stating that canonical line items come from the
versioned taxonomy and pointing at its module; the taxonomy file itself carries the definitions.
Note the unmapped-item policy in `CLAUDE.md` conventions if contributors would otherwise be tempted
to "fix" an unmapped item by adding a loose mapping.

## Completion notes
_Not started._
