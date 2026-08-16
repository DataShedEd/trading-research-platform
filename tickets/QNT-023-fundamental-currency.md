# QNT-023 — Fundamental currency handling

- **Ticket ID:** QNT-023
- **Status:** DONE
- **Priority:** P1
- **Epic:** EPIC 4 — Fundamental Data

## Problem
Reporting currency and quotation currency are routinely different: Shell is a UK-listed company
reporting in US dollars and quoted in pence; plenty of European names report in euro while listing
in several currencies. A value factor that divides a dollar-denominated equity figure by a
sterling market capitalisation is wrong by roughly the exchange rate, and the error is silent
because both numbers look plausible. Converting at ingestion time is equally wrong in a different
way: it bakes one rate, on one date, from one source, into the canonical store, destroys the
reported figure, and makes the whole dataset unreproducible when the FX source is revised.

## Objective
Store fundamental values in the currency in which they were reported, never converting at
ingestion, and provide conversion at query/derivation time using dated FX rates, so that a
mixed-currency universe produces arithmetically consistent factors.

## Scope
`src/trp/canonical/fundamentals/currency.py`: a `convert_fundamentals` helper taking canonical
fundamental rows, a target currency, and an FX rate source, returning converted values tagged with
the rate, rate date and FX source used; the rule for which date's rate applies; guards that refuse
to mix currencies in an aggregate; unit tests and a mixed-currency scenario test.

## Out of scope
Ingestion-time conversion of any kind (explicitly forbidden by this ticket); the FX rate store and
its loaders (QNT-017); price-side currency handling and the pence/pound `GBX` quotation issue on
the market-data side (Epic 3); factor definitions that consume converted values (Epic 8).

## Acceptance criteria
- [x] No code path writes a converted fundamental value into `data/canonical/fundamentals/`: the
      stored `currency` is always the reporting currency as filed, and a test asserts that
      ingestion of a USD-reporting UK company yields USD rows.
- [x] `convert_fundamentals` converts at query/derivation time only, and its output records the
      target currency, the rate applied, the rate's effective date, and the FX source, so a
      converted figure can be reproduced exactly.
- [x] The conversion date rule is documented and implemented: a flow item (income statement, cash
      flow) and a stock item (balance sheet) may legitimately use different rate conventions, and
      whichever convention is chosen is applied consistently and stated in the docstring.
- [x] Conversion is point-in-time safe: the rate used is one available at the query's `as_of`, and
      converting with an `as_of` earlier than the rate's availability raises rather than reaching
      forward for a later rate.
- [x] A missing rate is an explicit failure or an explicitly-flagged null — never a silent
      passthrough of the unconverted number, and never a value carried forward from an arbitrarily
      distant date beyond a documented staleness tolerance.
- [x] A mixed-currency universe test covers a UK-listed, USD-reporting company (Shell) alongside a
      GBP-reporting UK company and a EUR-reporting European company, asserting that the resulting
      converted values are consistent and that combining unconverted mixed-currency rows raises.

## Technical notes
`docs/DATA_MODEL.md` gives fundamentals a `currency` field precisely so the reported figure
survives; this ticket makes that non-negotiable. Conversion at the boundary follows the same
principle as adjusted prices in QUANT_PRINCIPLES §3: derived views are computed from stored facts,
never substituted for them.

Per DEC-005, rates and converted values are `Decimal`. Rounding must be explicit — decide and
document the quantisation applied after multiplication rather than letting `Decimal` context
defaults decide, and never round-trip through `float`.

Point-in-time correctness applies to FX exactly as it does to fundamentals: an FX rate has its own
availability, and a conversion performed for a backtest dated 2015 must use a 2015 rate, not
today's. Where the FX series from QNT-017 carries no explicit availability, treat the rate for date
*d* as available at the close of *d* in UTC terms and document the assumption; err late, per
DEC-007's spirit.

The Shell case is the canonical test because it exercises three different currencies at once:
reporting currency USD, quotation currency GBX (pence), and a research base currency of GBP. Any
factor combining a fundamental with a market price must convert both sides into the same currency
explicitly; make it impossible to do so implicitly by refusing to aggregate rows whose `currency`
values differ.

A company can change reporting currency between periods. That is not a revision (QNT-022's key
excludes currency) and must not be treated as one; the correct behaviour is that each period keeps
its own reporting currency and conversion handles the rest. Cover it in tests.

## Dependencies
QNT-020 — the fundamental record and its `currency` field. QNT-017 — dated FX rates, without which
conversion has no source; until it lands, the helper is developed against a fixture rate table
implementing the same interface.

## Risks
The largest risk is a plausible-looking wrong number: a factor computed from an unconverted mixed
pair passes every type check. Mitigated by refusing mixed-currency aggregation at the API level
rather than relying on caller discipline. A second risk is FX availability being assumed rather
than modelled, quietly reintroducing look-ahead; mitigated by the `as_of` guard and the time-travel
test.

## Testing requirements
`tests/canonical/test_fundamental_currency.py` for conversion arithmetic, rounding, missing-rate
behaviour, mixed-currency refusal, and the reporting-currency-change case, plus
`tests/timetravel/test_fundamental_currency_asof.py` (pytest marker `timetravel`) asserting that no
conversion uses a rate whose availability postdates `as_of`. The mixed-currency scenario fixture
(Shell in USD, a GBP reporter, a EUR reporter) lives in `tests/fixtures/` and should reuse the
validation-universe entries from QNT-027 where they overlap.

## Documentation requirements
`docs/DATA_MODEL.md` states that fundamental values are stored as reported and converted only at
query time, and names the conversion-date convention. `docs/QUANT_PRINCIPLES.md` needs no change,
but add a `DECISIONS.md` entry recording the flow-versus-stock rate convention and the FX
availability assumption, since both constrain every factor built later.

## Completion notes

**2026-08-16 — done.**

Delivered `src/trp/canonical/fundamentals/currency.py`:

- `convert_fundamentals(frame, *, to_currency, fx, as_of, ...)` takes a result frame from
  `trp.canonical.fundamentals.queries.fundamentals` and returns it with every input column intact
  plus `target_currency`, `converted_value`, `fx_rate`, `fx_rate_date`, `fx_rate_available_at`,
  `fx_source`, `unit_kind`, `converted` and `conversion_note`. The reported `currency` and `value`
  stay beside the converted figure, so any converted number is reproducible from the row alone.
- Conversion reuses QNT-017 end to end: `Money`, `ReferenceData` unit scaling and
  `convert_with_fx` do the arithmetic (subunit → major → rate → target unit), so GBX/GBP is the
  existing exact decimal-point shift and there is no second FX or pence policy. A tiny
  `_RecordingFx` wrapper captures the rate that was used for the audit columns instead of asking
  the provider twice.
- **Conversion date rule:** the spot rate for the row's own `period_end`, applied to flow and
  stock items alike, stated in the module docstring. Average-rate conversion for flow items is the
  theoretically better treatment but needs a daily FX series we do not have; mixing conventions
  would be worse than one stated one. Revisit deliberately (and versioned) when a series lands.
- **FX availability:** a rate for date *d* is knowable from 00:00 UTC on *d+1* — after *d*'s close,
  erring late per DEC-007's spirit. `fx_available_at` is the single place that assumption lives.
  A conversion whose `as_of` precedes it raises `FxRateNotYetAvailableError` and the provider is
  never even asked; the guard is unconditional, since `strict` governs missing data, not leakage.
- **Missing rate:** raises by default (QNT-017's own `FxRateUnavailableError`, with row context
  attached via `add_note`); `strict=False` yields a flagged null with the reason, never a
  passthrough of the unconverted number and never a rate carried forward from another date.
- **Rounding (DEC-005):** arithmetic in a 60-digit local decimal context, quantised exactly once
  to six decimal places (the store's `Decimal(38,6)` scale) with `ROUND_HALF_EVEN`. `fx_rate` is
  recorded as an exact decimal *string* — a fixed-scale column would silently round a rate quoted
  to more places, and a rounded audit record is worthless. Nothing touches `float`.
- **Unit kinds:** rows whose canonical line item is a `share_count` or `ratio` in the QNT-021
  taxonomy are passed through unconverted and flagged. FX-multiplying a share count is exactly the
  plausible-wrong-number class this ticket exists to prevent. Line items absent from the taxonomy
  are treated as currency amounts and labelled `unknown`, so the assumption is visible.
- **Mixed-currency guard:** `require_single_currency` and `total` (returning `Money`) refuse to
  combine rows across currencies.

Storage was not touched: QNT-024 stores what it is given, and a test asserts byte-for-byte that
conversion leaves the store unchanged.

Tests: `tests/canonical/test_fundamental_currency.py` (14) and
`tests/timetravel/test_fundamental_currency_asof.py` (4, marker `timetravel`) — 18 passing.
The mixed-currency fixture is `tests/fixtures/currencies.py`: a Shell-like UK-listed USD reporter,
a GBP reporter stating EPS in pence, and a EUR reporter that switches to USD reporting for FY2020
(a currency change between periods, handled period by period and explicitly not a revision).
Covered: converted values consistent across all three reporters, pence→pounds exact with no FX
call, pence→USD through the major currency, share counts refused, missing rate raising and
flagging, explicit rounding, unconverted mixed rows refusing to combine, and the as-of guard
including that non-strict mode does not soften it.

Deviations and notes:

- Wired as a standalone `convert_fundamentals` on the query result rather than a `target_currency`
  parameter on `queries.fundamentals`. It composes cleanly (the query stays the single as-of choke
  point and gains no FX dependency) and keeps unconverted rows the default, which is the safer
  default. Adding an optional parameter later is a one-liner over this function.
- `markets.json` (QNT-017) defines only GBP/GBX/USD, so the euro reporter's tests build reference
  data with EUR added in `tests/fixtures/currencies.py`. **Ingesting a real euro reporter needs a
  EUR entry added to `src/trp/domain/reference_data/markets.json`** — flagged for the QNT-017 owner
  rather than edited here.

**Docs the coordinator should update** (this ticket was scoped to new files only):

- `docs/DATA_MODEL.md`, fundamentals section: values are stored as reported and converted only at
  query time via `trp.canonical.fundamentals.currency.convert_fundamentals`; the convention is
  period-end spot for every statement; converted output carries the rate, its date, its
  availability and its source alongside the original.
- `docs/DECISIONS.md`, new entry (DEC-012 or next free): the flow-versus-stock rate convention
  (period-end spot for both, average-rate deferred until a daily FX series exists) and the FX
  availability assumption (a rate for date *d* is knowable from 00:00 UTC on *d+1*), plus the
  six-decimal-place `ROUND_HALF_EVEN` quantisation and the exact-string `fx_rate` audit column.
  Both constrain every factor built later.
