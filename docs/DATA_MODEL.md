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

- **prices_daily** (implemented: QNT-013, `trp.domain.prices` / `trp.canonical.prices`) —
  `security_id`, `trade_date`, `open`/`high`/`low`/`close` as **raw as-traded Decimals**
  (Parquet `Decimal(18,6)`, pinned), `volume` (whole shares, `Int64`; fractional volume is
  rejected, never rounded), `currency` (quotation unit as traded — GBX for LSE pence, no
  implicit conversion), `source`, `ingested_at` (UTC), and optional
  `provider_adjusted_close` retained purely as a cross-check for our own adjustment factors.
  Invariants reject impossible bars (high/low/open/close ordering, zero or negative prices);
  a flat zero-volume bar is valid. Nothing ever mutates these values — adjusted prices are
  derived (QNT-015).
- **corporate_actions** (implemented: QNT-014, `trp.domain.corporate_actions`) — a
  discriminated union keyed on `action_type`: split, dividend (ordinary/special flag),
  rights issue, merger, delisting, ticker change. Common fields: `security_id`, `ex_date`
  (the adjustment date — first date traded without entitlement), optional
  `record_date`/`pay_date` (validated ≥ ex-date), `source`, `available_at` (UTC) with
  `available_at_imputed` per DEC-007 (imputed as start of ex-date UTC when the source gives
  none). **Ratio convention:** exact integer pairs, `new_shares` per `old_shares` — 2-for-1
  split = (2,1); 1-for-10 consolidation = (1,10); exposed as `Fraction` so cumulative
  adjustment products stay exact. Monetary terms always carry currency/quotation unit;
  merger consideration is cash (with currency), a share ratio (integer pair), or both.
- **adjustment_factors** (implemented: QNT-015, `trp.derived.adjustments`) — derived from
  corporate actions, stored as data under `data/derived/`, never in-place mutation.
  Backward-cumulative convention: the latest bar date has factor exactly 1; for date `d` the
  split factor is the product over splits with `ex_date > d` of `old_shares/new_shares`, and
  the dividend factor the product of `1 - D/P` (P = raw close of the last bar before the
  ex-date, expressed post-split when a split shares the ex-date — split composes first).
  Derivation is exact `Fraction` arithmetic; split factors persist as integer pairs;
  `factors_to_float_frame` is the single sanctioned Decimal→float boundary. Computation
  requires `as_of` and excludes actions with `available_at > as_of`; each persisted factor
  set carries provenance (as_of, input counts, ingestion timestamps, warnings) and is never
  overwritten. Rights issues are NOT adjusted (DEC-009) — affected securities are flagged.
  A reconciliation diagnostic compares our adjusted series against any provider-supplied
  adjusted close without ever tuning to it.
- **trading_calendars** (implemented: QNT-016, `trp.canonical.calendars`) — per exchange:
  trading days, holidays, half-days. Not a stored table: calendars are computed locally by
  the `exchange-calendars` library (DEC-010), wrapped and cached one instance per MIC by
  `get_trading_calendar`. Keyed by MIC with an explicit MIC → library-code map; `XLON`,
  `XNYS` and `XNAS` are supported and an unknown MIC raises. Supported range is fixed at
  2000-01-01 to 2030-12-31 for all three (LSE holiday data before ~2000 is patchy in every
  source); a query outside it raises `DateOutOfCalendarRange` rather than falling back to
  weekday logic. Trading days are market-local `date` values (DEC-005) — no session times
  are exposed. `sessions_between` is inclusive of both endpoints. A half day is a session
  shorter than the exchange's usual session length, and is still a trading day.
- **exchanges / currencies** — MIC, name, country, currency, timezone; FX rates for conversion.

## Fundamentals (point-in-time)

- **fundamentals** (record implemented: QNT-020, `trp.domain.fundamentals`) — subject is
  `security_id` (entity-level analysis goes via the master's entity link); statement enum
  (income | balance | cash_flow), canonical line item (taxonomy: QNT-021), `period_end`
  (date, market-local), period type (annual | interim | quarterly), reporting currency,
  `value` (strict Decimal — float input rejected), `filed_at` (provider's claim,
  informational), **`available_at`** (required, UTC-aware — the ONLY field as-of queries
  filter on; never fall back to `filed_at` or `period_end`), `revised_at` +
  `revision_sequence` (0 = original filing; >0 requires `revised_at`), `source`,
  `availability_imputed` + `imputation_rule` (set together, DEC-007; rule identifiers like
  `uk-annual-lag-90d` let QNT-035 measure the assumption). `available_at < period_end` is
  rejected as a data error. Series-level rules (contiguous sequences, strictly increasing
  `revised_at`) are enforced by `check_revision_series`.
- **Revision handling** (QNT-022, `trp.canonical.fundamentals.revisions`): the revision key
  is (security, statement, line item, period end, period type) — currency is NOT part of it;
  a currency change on the same key is a data error. `classify_observations` distinguishes
  new fact / unchanged re-observation (exact Decimal comparison, exponent-normalised — 100
  and 100.00 are one fact) / revision (appended with next sequence; its `available_at` is
  the restatement's own first-known time, strictly later than the previous revision's).
  Append-only end to end: revisions are new rows, never updates, and querying `as_of` a date
  between original filing and restatement returns the original figures.
- **Storage** (QNT-024, `trp.canonical.fundamentals.storage`): DEC-011 — year-partitioned
  append-only part-files, Decimal(38,6), idempotent writes keyed on (revision key, sequence),
  staged-rename atomicity, `_ingestion_log.jsonl` per write.
- **Query API** (QNT-025, `trp.canonical.fundamentals.queries`): `fundamentals(...)` is the
  ONLY supported read path — mandatory `as_of`, single choke-point predicate, latest knowable
  revision per key, provenance columns in every result; empty for too-early `as_of`, raises
  for unknown line items.

## Universes (implemented: QNT-037/038, `trp.universe`)

- **universe_membership** — universe name (registered centrally — a typo raises, never a
  silently empty universe), `security_id`, half-open `[valid_from, valid_to)` spell
  (`valid_to=None` = current member, a genuine null on disk), mandatory `source`
  provenance, plus the bitemporal knowledge axis (`recorded_at`/`superseded_at`, DEC-008).
  Invariant: non-overlap per (universe, security) — never uniqueness; re-entry is two
  spells. Storage: one deterministic Parquet file per universe under
  `data/canonical/universes/universe=<NAME>/`; wholesale rewrites are byte-identical;
  security ids must resolve in the master; `close_open_spell` is the only sanctioned
  mutation.
- **Query** (`trp.universe.query.UniverseQuery` — the sole supported access path):
  `members(universe, date, *, as_of)` answers from historical constituent data only, with
  `date` (event time) and `as_of` (knowledge time) independent; a date before coverage
  raises `UniverseCoverageError` rather than returning an empty set; unknown names raise
  listing the registered universes. `membership_changes` replays exactly between any two
  member sets; results cached per (universe, date, as_of, dataset version).

## Derived

- **factors** (framework implemented: QNT-042, `trp.factors`) — definitions are immutable
  JSON configuration under `config/factors/` (DEC-015): name, version, inputs, transform
  identifier, parameters, and a content hash that detects in-place edits at load. Transforms
  are a closed, enumerable registry of named Python implementations; `as_of` belongs to the
  compute surface, not individual factors. Every persisted value is tagged
  (`factor`, `factor_version`, `end`, `as_of`, input dataset versions) — untagged frames
  cannot be written — and versions coexist under
  `data/derived/factors/name=<n>/version=<v>/`. No permanent hard-coded composite.
- **returns** (implemented: QNT-043, `trp.factors.returns`) — THE single definition of a
  return for factors, risk and backtests. Price returns are split-adjusted; total returns
  add dividends under the reinvestment convention (reinvested at ex-date price). Windows
  are calendar months with a skip (`WindowSpec(12, 1)` = 12-1 momentum), endpoints resolved
  to the last bar on-or-before each date within a staleness cap. Explicit typed statuses:
  `insufficient_data` below a session-coverage threshold (never a silently wrong number,
  never forward-filled across a delisting), `delisted_no_proceeds` where an exit's value is
  unknowable; failures return −100%, cash acquisitions return through proceeds converted
  exactly to the quote unit. Dividends are unit-aligned to the bar's quote currency before
  factor computation (the GBP-dividend-on-GBX-price 100× trap, tested); non-sterling
  dividends are excluded with a warning pending QNT-023 FX wiring. Every computation takes
  `as_of`: actions published later cannot change earlier results (timetravel-tested).
- **experiments** — hypothesis, full parameterisation, data/code versions, results, conclusion
  (Epic 10; schema defined in its tickets).
