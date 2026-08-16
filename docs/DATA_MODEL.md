# Data model (canonical layer)

Conceptual schemas; authoritative definitions live in `trp.domain` as typed models and evolve
via tickets. Raw provider payloads are stored as received and are **not** described here.

## Security master

The spine of the system. A ticker is never a permanent identifier.

- **entity** — the company: `entity_id` (internal, immutable), name history, country of
  incorporation.
- **security** — an instrument issued by an entity: `security_id` (internal, immutable, never
  reused), `entity_id`, type (ordinary share, ADR, …), status (active, delisted, acquired, …)
  with status effective dates.
- **listing** — a security trading on an exchange: `security_id`, exchange (MIC), currency,
  `valid_from`/`valid_to`, delisting date and reason where known.
- **identifier_map** — external identifiers with effective ranges: `security_id`, kind
  (ISIN | SEDOL | CUSIP | ticker+exchange | provider-specific), value, `valid_from`/`valid_to`,
  source. Ticker changes are two rows, not an update.

Resolution: (external identifier, date) → `security_id`; reverse lookup returns the identifiers
valid on a date. Both take `as_of` where knowledge of the mapping itself is time-dependent.

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
