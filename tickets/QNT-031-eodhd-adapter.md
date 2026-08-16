# QNT-031 — EODHD provider adapter

- **Ticket ID:** QNT-031
- **Status:** BACKLOG
- **Priority:** P1
- **Epic:** EPIC 5 — Data Provider Bake-Off

## Problem
EODHD is a leading candidate specifically because it advertises delisted-security coverage and
broad international market breadth — the two things most providers handle worst and this platform
needs most. Those claims are unverified, and they cannot be verified until the bake-off harness can
actually call the API. Without an adapter, EODHD's place in the evaluation rests on its marketing
copy, which `docs/DATA_PROVIDER_EVALUATION.md` explicitly refuses to accept as evidence.

## Objective
Implement `MarketDataProvider` for EODHD — EOD prices, splits and dividends, fundamentals, and
delisted-security lists — handling transport, authentication, pagination and rate limits only, with
no semantic normalisation whatsoever.

## Scope
`src/trp/providers/adapters/eodhd.py`: the adapter class, its capability declaration, endpoint
mapping for the six interface methods, authentication via `Settings` (`SecretStr`), pagination and
retry/backoff, mapping of HTTP and API error conditions onto the shared exception taxonomy, and the
per-request metadata the raw store needs. Recorded/stub response fixtures and tests.

## Out of scope
Any normalisation, renaming, unit conversion or type coercion of payload contents — that belongs to
`trp.canonical` (QNT-021 for fundamentals, Epic 3 for market data); the checks that judge the data
(QNT-034, QNT-035); scoring (QNT-030); purchasing the subscription (owner decision, QNT-028).

## Acceptance criteria
- [ ] The adapter implements every `MarketDataProvider` method or explicitly declares the
      capability unsupported, with the declaration reflecting the subscribed tier rather than the
      full published product range.
- [ ] Payloads reach the raw store byte-identical to the API response: no JSON re-serialisation, no
      key reordering, no numeric parsing on the way through; a test compares stored bytes with the
      recorded fixture exactly.
- [ ] Authentication uses the API key from `Settings` as a `SecretStr`, and the key appears in no
      log line, no exception message, no stored request metadata and no test artefact — asserted by
      a test that greps captured logs and written files for a known sentinel key value.
- [ ] Pagination, rate limiting and transient errors are handled in the adapter: paged endpoints
      are followed to completion, HTTP 429 and the provider's quota responses raise
      `ProviderRateLimitError`, 5xx and timeouts retry with bounded exponential backoff, and
      persistent failure raises `ProviderUnavailableError` rather than returning partial data
      silently.
- [ ] Delisted-security retrieval is implemented as a first-class method — enumerating delisted
      tickers for a market and fetching their price history to the delisting date — because it is
      the highest-weighted criterion in the rubric.
- [ ] All tests run against recorded or stubbed responses with no live API calls, CI fails if a
      test attempts network access, and the recorded fixtures are checked in with the date and
      endpoint they were captured from and with any key redacted.

## Technical notes
`docs/ARCHITECTURE.md` is unambiguous that adapters translate transport, auth and pagination only.
The temptation with EODHD is to tidy its fundamentals payload, which is deeply nested and awkward
to consume; resist it entirely. The nesting is data about the provider that QNT-035's checks will
measure, and flattening it here would both destroy evidence and hide the cost of using this
provider.

The adapter should surface whatever filing or announcement timestamps the fundamentals endpoints
contain, untouched and unparsed, since their presence is exactly what QNT-035 measures and what
DEC-007 imputation exists to compensate for when they are absent.

Note the UK pence/pound quotation question: EODHD's LSE prices may be quoted in GBX, GBP, or
inconsistently between endpoints. Do not correct it in the adapter — record what arrives, and let
the check layer establish the truth, since a silent unit correction here would mask a real data
quality finding.

Ticker syntax is provider-specific (exchange-suffixed codes). Mapping from the validation
universe's identifiers to EODHD's symbol format is transport-level work and belongs here, but it
must be explicit, testable, and recorded in the request metadata so a failed lookup can be
distinguished from a wrong symbol — a distinction that materially changes the identifier-stability
score.

Per-request metadata must include endpoint, parameters (key excluded), and UTC fetch timestamp for
the raw store (QNT-026). Retry attempts should be visible in that metadata too, since API
reliability is a scored criterion.

Development can proceed against recorded fixtures before a subscription exists; only the live
validation run is genuinely blocked.

## Dependencies
QNT-026 — the `MarketDataProvider` interface, exception taxonomy and raw store. QNT-028 — the
research report and the owner's subscription decision that supplies the API key and determines the
tier.

## Risks
**Expected BLOCKED-on-keys until the owner decision from QNT-028.** A paid API key is required for
any live run, so this ticket can be implemented and unit-tested against fixtures but cannot be
validated end to end until the subscription exists; sequence it accordingly and do not let the
blocked state stall QNT-029's harness work. Secondary risk: the subscribed tier may not include
datasets the published documentation implies, so capability declarations may need revising after
the first live run. Third: fixtures recorded from a trial tier may not represent paid-tier response
shapes.

## Testing requirements
`tests/providers/test_eodhd_adapter.py` using recorded/stubbed responses: byte-fidelity of stored
payloads, pagination across multiple pages, 429 and 5xx handling with backoff, capability errors,
symbol mapping, and secret absence from logs and files. No live calls in CI. No `timetravel` marker
applies — the adapter fetches rather than serving historical queries — but tests must assert that
fetch timestamps recorded for the raw store are timezone-aware UTC, since availability reasoning
downstream depends on them.

## Documentation requirements
A short adapter README or module docstring recording endpoints used, the tier assumed, observed
rate limits, and any known payload quirks discovered while implementing — this feeds QNT-036's
report. `docs/DATA_PROVIDER_EVALUATION.md` provider notes updated with anything the implementation
reveals that the desk research got wrong.

## Completion notes
_Not started._
