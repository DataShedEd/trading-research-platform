# QNT-021 — Financial statement normalisation model

- **Ticket ID:** QNT-021
- **Status:** DONE
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
- [x] A canonical taxonomy exists covering, at minimum, the line items needed for value and
      quality factors across all three statements, each entry carrying statement membership, a
      one-line definition, a unit kind (currency amount | share count | ratio) and a documented
      sign convention.
- [x] Provider mappings live in data files, not Python `if`/`dict` literals embedded in transform
      code; each mapping entry records provider item name, canonical item, and a mapping-confidence
      or review status; the loader validates every file against a schema at load time and fails
      loudly on an unknown canonical name or duplicate provider key.
- [x] Normalising the same fixture payload twice produces byte-identical canonical output
      (deterministic ordering, no dependence on dict iteration or wall-clock time).
- [x] An item with no mapping is never dropped and never guessed: it is returned in an explicit
      unmapped collection carrying the raw provider name and value, is counted in a summary that
      the caller can log or assert on, and does not appear under a canonical name.
- [x] Mapping tables are versioned — the taxonomy and each mapping file carry a version identifier
      that is recorded on normalisation output, so a canonical row can be traced to the mapping
      version that produced it.
- [x] Unit tests cover a full fixture payload mapping deterministically, an unmapped item being
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

**2026-08-16 — done.**

Delivered:

- `src/trp/canonical/fundamentals/line_item_taxonomy.json` — the taxonomy as data, v1.0, 21
  entries across all three statements (revenue → free_cash_flow, plus share counts and per-share
  amounts). Every entry carries statement membership, a one-line definition, a unit kind
  (`currency_amount` | `per_share_amount` | `share_count` | `ratio`) and a sign convention.
- `src/trp/canonical/fundamentals/taxonomy.py` — models and loaders for the taxonomy and for the
  provider mapping tables, with all cross-file validation in the loader: unknown canonical name,
  canonical item on the wrong statement, duplicate `(statement, provider_item)` key, two provider
  items claiming one canonical item, a table written against a different taxonomy version, and a
  file whose declared provider disagrees with its filename all raise `MappingTableError`.
- `src/trp/canonical/fundamentals/mappings/{eodhd,fmp}.json` — mapping tables as data, keyed on
  `(statement, provider_item)` because providers reuse names across statements. Every entry
  carries an explicit `sign` flag and a `review_status`; **every shipped entry is
  `provisional`**, because the names were taken from provider documentation and not from recorded
  payloads. QNT-031/032 must confirm each field name, statement and sign against real captured
  JSON before promoting entries to `verified`; the EODHD capex sign flip is called out in the file
  as the highest-risk entry.
- `src/trp/canonical/fundamentals/normalisation.py` — `normalise_line_items`, returning mapped
  items (sorted, deterministic, each stamped with taxonomy and mapping version) plus an explicit
  `unmapped` collection and a counted summary. `sign_violations` surfaces values that contradict
  their taxonomy convention as data rather than raising. `to_fundamental_value` builds the QNT-020
  record from a mapped item plus the caller's period/availability facts.

Deliberate design choices beyond the ticket text:

- **A fourth unit kind, `per_share_amount`.** EPS is money per share, and the distinction is
  load-bearing for QNT-023: monetary kinds convert by an FX rate, share counts and ratios never do.
- **`canonical: null` + `review_status: excluded`** distinguishes "we looked at this and refuse to
  map it" (the cash flow statement's repeat of net income) from "nobody has considered it". Both
  come back unmapped; only the second needs a human.
- **No scale factor.** A provider reporting in thousands is real, but modelling it before it is
  seen in a recorded payload means applying a multiplier on faith. Noted in the module docstring
  as the thing to add when an adapter needs it.
- Payload-level duplicates (`(statement, provider_item)` twice in one payload) raise rather than
  one silently winning.

Tests: `tests/canonical/test_fundamental_taxonomy.py` (8) and
`tests/canonical/test_provider_mapping.py` (21) — 29 passing. Fixtures:
`tests/fixtures/provider_payload.py` (a checked-in synthetic payload with mappable items, a
sign-inverted capex, a deliberately-excluded item and an unmapped one) and
`tests/fixtures/mappings/stub.json`. Coverage includes byte-identical re-normalisation,
unmapped items surfaced and counted, every loader rejection above, the capex sign case, a wrong
sign flag showing up in `sign_violations`, and an assertion that no model in the normalisation
path has a temporal field and the module never reads the clock.

Deviations: none material. The ticket's suggested `mappings/<provider>.<ext>` layout is followed;
the taxonomy data file sits beside `taxonomy.py` as `line_item_taxonomy.json` (a directory would
have collided with the module name).

**Docs the coordinator should update** (this ticket was scoped to new files only, so `docs/` was
not touched):

- `docs/DATA_MODEL.md`, fundamentals section: canonical line items come from the versioned
  taxonomy at `trp.canonical.fundamentals.taxonomy` (data in `line_item_taxonomy.json`, provider
  tables in `mappings/`); normalisation output records taxonomy and mapping version; unmapped
  provider items are preserved and counted, never coerced.
- `CLAUDE.md` conventions: the never-coerce rule — an unmapped provider item is fixed by adding a
  reviewed mapping entry or by leaving it unmapped, never by loosening an existing mapping.
