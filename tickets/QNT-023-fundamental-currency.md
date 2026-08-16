# QNT-023 — Fundamental currency handling

- **Ticket ID:** QNT-023
- **Status:** BACKLOG
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
- [ ] No code path writes a converted fundamental value into `data/canonical/fundamentals/`: the
      stored `currency` is always the reporting currency as filed, and a test asserts that
      ingestion of a USD-reporting UK company yields USD rows.
- [ ] `convert_fundamentals` converts at query/derivation time only, and its output records the
      target currency, the rate applied, the rate's effective date, and the FX source, so a
      converted figure can be reproduced exactly.
- [ ] The conversion date rule is documented and implemented: a flow item (income statement, cash
      flow) and a stock item (balance sheet) may legitimately use different rate conventions, and
      whichever convention is chosen is applied consistently and stated in the docstring.
- [ ] Conversion is point-in-time safe: the rate used is one available at the query's `as_of`, and
      converting with an `as_of` earlier than the rate's availability raises rather than reaching
      forward for a later rate.
- [ ] A missing rate is an explicit failure or an explicitly-flagged null — never a silent
      passthrough of the unconverted number, and never a value carried forward from an arbitrarily
      distant date beyond a documented staleness tolerance.
- [ ] A mixed-currency universe test covers a UK-listed, USD-reporting company (Shell) alongside a
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
_Not started._
