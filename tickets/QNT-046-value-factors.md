# QNT-046 — Value factor set

- **Ticket ID:** QNT-046
- **Status:** DONE
- **Priority:** P2
- **Epic:** EPIC 7 — Factor Engine

## Problem
Value metrics combine a fundamental numerator with a market-price denominator, so they inherit
look-ahead risk from both sides. Using today's share count with a historical price, or a
market capitalisation recomputed after a restatement, produces a valuation nobody could have
observed at the time — and value factors are precisely the ones most sensitive to that error.

## Objective
Express a value factor set — earnings yield, free-cash-flow yield, EV/EBIT, EV/EBITDA, price-to-book
where meaningful, and shareholder yield — as versioned definitions, with market values built from
point-in-time prices and point-in-time shares outstanding.

## Scope
Definition files under `config/factors/value/` and their transforms; a shared point-in-time market
capitalisation and enterprise value helper (price at or before the date times shares outstanding
known at the date, plus net debt from the latest available balance sheet); yield-form conventions
(expressed as yields rather than multiples where a zero or negative denominator would otherwise
blow up); fixtures and tests.

## Out of scope
Fundamentals ingestion (QNT-025); price adjustment (QNT-015); cross-sectional standardisation
(QNT-047); composites (QNT-048); dividend-forecast or analyst-estimate-based valuation.

## Acceptance criteria
- [x] Six definitions exist as versioned configuration, each naming its numerator line items,
      denominator, and currency convention.
- [x] Market capitalisation and enterprise value use the price on or before the computation date and
      the shares outstanding available at that date; a test asserts that a later share-count
      restatement does not change a historical value.
- [x] Metrics are expressed as yields (earnings yield rather than P/E) wherever a negative or
      near-zero denominator would otherwise produce an unrankable value, and the remaining
      multiple-form metrics have a documented not-meaningful rule that is tested.
- [x] Shareholder yield combines dividends and net buybacks over a trailing window from
      point-in-time data, and its window and sign convention are stated in the definition.
- [x] Price-to-book is computed only where book value is meaningful, with the exclusion rule
      documented rather than silently producing a number.
- [x] Values match hand-computed fixtures, including a `GBX`-quoted security and one with a
      non-`GBP` reporting currency.

## Technical notes
Currency is the recurring trap: prices may be quoted in pence while financial statements are
reported in pounds, euros, or dollars. Every value definition must state the conversion path, and
conversion must use rates dated at or before the computation date.

Enterprise value needs net debt from the latest balance sheet available at the date, which will
usually be several months stale relative to the price. That staleness is correct and must not be
"improved" by using a later balance sheet.

## Dependencies
QNT-042 — supplies the definition framework and version tagging.
QNT-025 — supplies point-in-time fundamentals and shares outstanding.

## Risks
Value factors are highly sensitive to the availability lag applied to fundamentals; too short a lag
flatters results substantially. Mitigated by relying on the conservative imputed `available_at` from
QNT-025 rather than any local assumption, and by asserting the dependency in the time-travel tests.

## Testing requirements
`tests/factors/test_value.py` — hand-computed fixtures per metric; negative-earnings and
negative-book cases; `GBX` and foreign-reporting-currency cases; shareholder-yield window.

`tests/timetravel/test_value_factors.py` (marker `timetravel`) — values at date *t* are unchanged by
prices, filings, restatements, or share-count revisions dated after *t*; the enterprise value at *t*
uses the balance sheet available at *t* even when a newer one exists in the fixture.

## Documentation requirements
Factor catalogue entries recording each metric's formula, currency convention, yield-versus-multiple
form, and not-meaningful rules.

## Completion notes
2026-08-21. Six v1 definitions under config/factors/value/ via the `market_value_yield`
transform: earnings_yield, fcf_yield, ebit_ev_yield, ebitda_ev_yield (yield forms — a
negative numerator ranks naturally, EV <= 0 refuses), book_to_market (negative book value
is a typed exclusion with the reason in warnings), shareholder_yield (dividends_paid +
share_buybacks over the latest reported year, negated so positive = cash returned and net
issuance is a negative yield). PIT on both sides: market cap = raw GBX close on or before
t (DEC-020 source) / 100 x shares outstanding AVAILABLE at t (later share-count
restatements provably inert); EV adds net_debt from the balance sheet available at t even
when a newer one exists in the fixture (timetravel-tested, exactly the staleness the
ticket demands). NEW dated-FX dataset for the currency trap: `trp.canonical.fx` ingests
GBPUSD (2002->) and GBPEUR (1986->) raw-first into data/canonical/fx/ with sanity bands;
conversion uses the last rate on or before t and REFUSES stale (>7 days) or missing rates
as no_data with the reason — never an invented rate. Hand fixtures include a GBX-priced
GBP reporter and a USD reporter at a fixed fixture rate; `fx` added to KNOWN_INPUTS.
Real FTSE 100 cross-section (2020-06-30, gate-tested): 94-99/100 computable, medians
earnings yield 5.2% (P/E ~19), book-to-market 0.44, EBITDA/EV 9.5%, shareholder yield
4.8%. Backtest-runner wiring of fundamentals_root/fx_root arrives with the composite
work (QNT-047/048), where a value strategy first runs end-to-end. 797 default + 21 gate
green.
