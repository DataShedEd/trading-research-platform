# QNT-017 — Exchange and currency metadata

- **Ticket ID:** QNT-017
- **Status:** BACKLOG
- **Priority:** P1
- **Epic:** EPIC 3 — Market Data

## Problem
LSE ordinary shares are quoted in pence while dividends and market capitalisation are frequently
reported in pounds. Mixing the two produces values wrong by a factor of one hundred — a classic
factor-research bug that survives casual inspection because a hundredfold error in a ratio often
still looks like a number. There is currently no reference data stating what unit an exchange quotes
in.

## Objective
Reference data for exchanges and currencies, an explicit and enforced GBX/GBP handling policy, and
an FX rate interface that later conversion work can implement against.

## Scope
`src/trp/domain/reference.py` defining `Exchange` (MIC, name, country, timezone, trading currency,
quotation unit) and `Currency` (ISO code, minor unit, whether it is a quotation subunit of another
currency); a committed reference data file for the exchanges in use; conversion helpers between a
quotation unit and its major currency; an `FxRateProvider` protocol with a documented signature and
no production implementation.

## Out of scope
Sourcing or storing actual FX rate history (a later ticket implements the protocol), multi-currency
portfolio accounting (Epic 6), exchanges beyond those the platform ingests.

## Acceptance criteria
- [ ] `Exchange` records exist for at least `XLON`, `XNYS`, and `XNAS`, each with MIC, name,
      country, IANA timezone, trading currency, and quotation unit, loaded from a committed data
      file rather than hard-coded in Python.
- [ ] `GBX` is modelled as a quotation subunit of `GBP` with a factor of exactly 100, and the
      relationship is data rather than a special case in conversion code.
- [ ] `to_major_currency(amount, unit)` converts 1234.5 GBX to exactly `Decimal("12.345")` GBP, and
      the round trip back to GBX is exact; a test asserts exactness rather than approximate
      equality.
- [ ] Conversion between unrelated currencies raises a typed error directing the caller to the FX
      interface, rather than returning the amount unchanged.
- [ ] `FxRateProvider` is a typed protocol taking a currency pair and a date and returning a
      `Decimal` rate, with the rate direction documented unambiguously; a test-only fixed-rate
      implementation exists for use in other suites.
- [ ] A test asserts that a price in GBX and a dividend in GBP cannot be combined without an
      explicit unit conversion — the arithmetic path either converts or raises, never assumes.

## Technical notes
The quotation unit belongs on the exchange and on every monetary value, not only on the exchange:
the same security can have a price quoted in pence and a dividend declared in pounds within the same
provider payload, which is exactly how the bug occurs in practice. QNT-013 and QNT-014 already carry
a currency field per record; this ticket makes those fields meaningful and gives them a conversion
path.

Conversion is exact `Decimal` scaling by a power of ten (DEC-005) — never a float multiply, and
never a rounding step. Converting 1234.5 GBX must yield 12.345 GBP with the third decimal intact,
because that third decimal is a real half-penny in the original quote.

The FX protocol is defined now and implemented later so that dependent code can be written against a
stable signature. Pin the direction convention in the protocol docstring — `rate(base, quote, date)`
meaning units of quote per unit of base — since an inverted FX rate is the same class of silent
hundredfold-style error as the pence bug.

Exchange timezone is stored for future intraday work and for reasoning about when a market-local
date maps to a UTC timestamp; Milestone 1 uses dates only, so nothing should depend on it yet.

## Dependencies
QNT-003 — settings supply the data-layer paths from which reference data is loaded.

## Risks
Reference data drifts — exchanges rename, MICs are retired. Mitigated by treating the file as
versioned repository data reviewed on change rather than as a live lookup, and by validating MICs
against the same rule QNT-006 applies.

## Testing requirements
`tests/domain/test_reference_data.py`. Mandatory: pence-to-pounds conversion exactness in both
directions; the unrelated-currency error; the reference file loading and validating for all three
exchanges; the FX protocol's test implementation satisfying the protocol under `mypy --strict`. No
`timetravel` test is required here as this data carries no knowledge-time axis, but the FX protocol
signature must include a date so its future implementation can be point-in-time correct.

## Documentation requirements
`docs/DATA_MODEL.md` `exchanges / currencies` section expanded with the GBX/GBP policy stated
explicitly. A short note in `CLAUDE.md` conventions flagging pence quotation as a known hazard.

## Completion notes
_Not started._
