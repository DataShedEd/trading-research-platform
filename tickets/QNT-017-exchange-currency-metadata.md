# QNT-017 — Exchange and currency metadata

- **Ticket ID:** QNT-017
- **Status:** DONE
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
- [x] `Exchange` records exist for at least `XLON`, `XNYS`, and `XNAS`, each with MIC, name,
      country, IANA timezone, trading currency, and quotation unit, loaded from a committed data
      file rather than hard-coded in Python.
- [x] `GBX` is modelled as a quotation subunit of `GBP` with a factor of exactly 100, and the
      relationship is data rather than a special case in conversion code.
- [x] `to_major_currency(amount, unit)` converts 1234.5 GBX to exactly `Decimal("12.345")` GBP, and
      the round trip back to GBX is exact; a test asserts exactness rather than approximate
      equality.
- [x] Conversion between unrelated currencies raises a typed error directing the caller to the FX
      interface, rather than returning the amount unchanged.
- [x] `FxRateProvider` is a typed protocol taking a currency pair and a date and returning a
      `Decimal` rate, with the rate direction documented unambiguously; a test-only fixed-rate
      implementation exists for use in other suites.
- [x] A test asserts that a price in GBX and a dividend in GBP cannot be combined without an
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
**2026-08-16 — done.**

Delivered `src/trp/domain/reference.py`, the committed reference file
`src/trp/domain/reference_data/markets.json`, tests in `tests/domain/test_reference_data.py`
(44 passing), and the test-only FX fake `tests/fakes/fx.py`.

- `Currency` carries ISO code, `minor_unit` (the ISO 4217 *settlement* exponent, explicitly not a
  quotation precision — LSE quotes half pence), and the optional pair
  `quotation_subunit_of` / `units_per_major`. GBX→GBP with factor 100 is therefore a row in the
  data file; conversion code contains no currency names at all.
- `units_per_major` must be a power of ten, validated at load. That is what makes conversion an
  exponent shift on the `Decimal` tuple rather than a division: exact for any value, at any
  context precision. A test sets `prec=5` and converts a 31-digit amount, asserting the result
  differs from what `amount / Decimal(100)` returns there.
- `Exchange` carries MIC (same `^[A-Z0-9]{4}$` rule `Listing` applies), name, ISO country, IANA
  timezone (constructed through `ZoneInfo` at validation, so a plausible-looking fake zone is
  rejected), trading currency and quotation unit. XLON is GBP/GBX; XNYS and XNAS are USD/USD.
- `ReferenceData` enforces cross-record invariants at load: unique MICs and codes, every named
  currency defined, no chained subunits, and an exchange quoting in a subunit of a *different*
  currency than it trades in is rejected. Seven malformed-file cases are tested.
- Unit conversion refuses two distinct ways, with distinct errors: `UnrelatedCurrencyError`
  (GBP↔USD — names `FxRateProvider` and `convert_with_fx` in the message) and
  `CurrencyMismatchError` (arithmetic across units, raised even for GBX/GBP so the caller states
  the result unit rather than inheriting the left operand's).
- `FxRateProvider.rate(base, quote, on)` returns units of quote per unit of base — multiply to go
  base→quote — with the direction, the point-in-time meaning of `on`, and the obligation to raise
  `FxRateUnavailableError` (never 1, never an inverse, never a nearest date) pinned in the
  docstring. No production implementation.

Deviations and things deliberately not done:

1. **Reference file location.** The ticket's dependency implies loading from a settings-supplied
   data path, but `data/` is gitignored, so a *committed* file cannot live there. It ships as
   package data under `src/trp/domain/reference_data/` and is read via `importlib.resources`;
   `load_reference_data(path)` takes an override path, which is where a settings-supplied location
   would plug in later. QNT-003 is therefore not actually exercised by this ticket.
2. **Scope added: `Money`.** A frozen `(amount, unit)` value type with `+`, `-` and `/` that raise
   across units. Without it the last acceptance criterion has nothing to assert against — "the
   arithmetic path raises" needs an arithmetic path. `Money` rejects `float` amounts outright
   (DEC-005) rather than coercing them, and rejects NaN/Infinity. `convert_with_fx` was added with
   it: it converts to the major currency, applies exactly one dated rate in the documented
   direction, then converts into the target unit, so the FX interface has a correct call site
   demonstrating the ordering. Tests assert the provider is asked for GBP/USD, never GBX/USD.
3. **Documentation requirements not met.** `docs/DATA_MODEL.md` (`exchanges / currencies`) and the
   `CLAUDE.md` conventions note on pence quotation are **outstanding** — both files are being
   edited concurrently by other ticket work in this session and this ticket was scoped to new
   files. The GBX/GBP policy is stated in the module docstring and in the `notes` field of
   `markets.json` in the meantime.
4. **No re-export from `trp/domain/__init__.py`** for the same concurrency reason; import from
   `trp.domain.reference` directly until that file is updated.
5. **mypy coverage of the test fake.** `uv run mypy` is configured with `packages = ["trp"]`, so it
   does not typecheck `tests/`. The protocol-conformance criterion was verified by running
   `uv run mypy --strict tests/fakes/fx.py tests/domain/test_reference_data.py` separately (clean),
   plus a runtime `isinstance` check against the runtime-checkable protocol.
6. No `timetravel` test, as the ticket states; the FX signature carries `on` so its future
   implementation can be point-in-time correct.

Checks run: `ruff check`, `ruff format`, `uv run mypy` (34 source files, clean),
`uv run pytest tests/domain/test_reference_data.py` — 44 passed.
