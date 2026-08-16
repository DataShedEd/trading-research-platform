# Data model (canonical layer)

Conceptual schemas; authoritative definitions live in `trp.domain` as typed models and evolve
via tickets. Raw provider payloads are stored as received and are **not** described here.

## Security master (implemented: QNT-006…011, `trp.domain`)

The spine of the system. A ticker is never a permanent identifier. `trp.domain` is the
authoritative definition; this section states the conventions.

**Conventions.** Event-time validity is half-open: `[valid_from, valid_to)`, `valid_to=None`
meaning open-ended (a genuine null in storage, never a sentinel date). Effective-dated records
are **bitemporal** (DEC-008): `recorded_at`/`superseded_at` (UTC) say when we believed the
record; revisions supersede, never delete, so any historical knowledge state is
reconstructable via `trp.domain.pit.known_as_of`. `recorded_at=None` (backfill) means
always-known.

- **entity** — `entity_id` (internal, immutable, `ENT-<uuid4>`), current name, ISO country.
  Name history as effective-dated records is future work.
- **security** — `security_id` (internal, immutable, never reused, `SEC-<uuid4>`, minted only
  by explicit `new_security_id()`), `entity_id`, type enum.
- **security_status** — effective-dated periods: active | suspended | delisted | acquired |
  liquidated, with free-text `reason` and `related_security_id` (e.g. the acquirer).
- **listing** — `security_id`, exchange MIC, quote currency as quoted (GBX for LSE pence),
  validity range, `delisting_reason` enum (failure | acquisition | voluntary | regulatory |
  exchange_move) — an enum so backtest accounting can branch on it.
- **identifier_map** — `security_id`, kind (ISIN | SEDOL | CUSIP | ticker+MIC | FIGI |
  provider), value, validity range, source. ISIN/SEDOL/CUSIP check digits are validated at
  construction. A ticker change is two rows, never an update; ticker reuse across disjoint
  periods is legal, overlap is not.

**Aggregate invariants** (`SecurityMaster`, enforced at construction): referential integrity;
no overlapping status periods or identifier claims among current records; nothing in force
past a terminal status date.

**Resolution** (`IdentifierResolver`): `(value, kind, date[, mic]) → security_id`; no match
and ambiguity are typed errors — never a guess, never a nearest-date fallback. Bulk
`resolve_many` returns failures as rows so callers must handle them. Point-in-time consumers
use `PointInTimeSecurityMaster`, whose every query takes a mandatory `as_of` knowledge
timestamp alongside the event date.

**Storage** (`trp.canonical.security_store`): five Parquet tables under
`data/canonical/securities/` — `entities`, `securities`, `listings`, `status_periods`,
`identifiers` — explicit schemas, deterministic ordering, staged-rename atomic writes, and a
DuckDB helper registering each as a view. Reads reconstruct domain models, re-running all
invariants.

## Prices and corporate actions

- **prices_daily** — `security_id`, trading date, open/high/low/close (raw, as traded),
  volume, currency, source, ingestion timestamp. Decimal values.
- **corporate_actions** — `security_id`, action type (split, dividend, special dividend, rights
  issue, merger, delisting, ticker change), ex-date, record/pay dates where known, terms
  (ratio, amount + currency), source, `available_at`.
- **adjustment_factors** — derived from corporate actions: per `security_id` and date, cumulative
  split and dividend adjustment factors. Adjusted prices/total returns are computed, not stored
  as the only truth; raw and adjusted are always distinguishable.
- **trading_calendars** — per exchange: trading days, holidays, half-days.
- **exchanges / currencies** — MIC, name, country, currency, timezone; FX rates for conversion.

## Fundamentals (point-in-time)

- **fundamentals** — `security_id` (or `entity_id`), statement (income | balance | cash flow),
  line item (normalised name), period end, period type (annual | interim | quarterly), currency,
  value (Decimal), `filed_at` (publication), **`available_at`** (first-known — the field every
  as-of query filters on), `revised_at` and revision sequence for restatements, source,
  imputation flag for conservatively-estimated availability.
- Revisions are new rows, never updates: querying `as_of` a date between original filing and
  restatement returns the original figures.

## Universes

- **universe_membership** — universe name, `security_id`, `valid_from`/`valid_to`, source.
  Supports `members(universe, date)` from historical constituent data only.

## Derived

- **factors** — factor name + definition version, `security_id`, date, value, inputs' data
  versions. Factor definitions are configuration, versioned; no permanent hard-coded composite.
- **returns** — price and total returns per security/date, flagged with adjustment provenance.
- **experiments** — hypothesis, full parameterisation, data/code versions, results, conclusion
  (Epic 10; schema defined in its tickets).
