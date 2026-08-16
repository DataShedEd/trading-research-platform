# QNT-032 — Financial Modeling Prep provider adapter

- **Ticket ID:** QNT-032
- **Status:** BACKLOG
- **Priority:** P1
- **Epic:** EPIC 5 — Data Provider Bake-Off

## Problem
FMP is a candidate mainly on the strength of its fundamentals breadth and price, and it is the
candidate whose point-in-time credentials most need testing: broad statement coverage served as a
current view of history is precisely the shape that produces confident, wrong backtests. Its
international and delisted coverage are also uncertain. None of this can be assessed without an
adapter, and `docs/DATA_PROVIDER_EVALUATION.md` will not accept the vendor's own description as
evidence.

## Objective
Implement `MarketDataProvider` for FMP — EOD prices, splits and dividends, fundamentals, and
delisted-security lists — handling transport, authentication, pagination and rate limits only, with
no semantic normalisation whatsoever.

## Scope
`src/trp/providers/adapters/fmp.py`: the adapter class, its capability declaration, endpoint
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
      a test that greps captured logs and written files for a known sentinel key value. Note that
      FMP passes the key as a query parameter, so URL logging is the specific hazard to close.
- [ ] Pagination, rate limiting and transient errors are handled in the adapter: paged endpoints
      are followed to completion, HTTP 429 and the provider's quota responses raise
      `ProviderRateLimitError`, 5xx and timeouts retry with bounded exponential backoff, and
      persistent failure raises `ProviderUnavailableError` rather than returning partial data
      silently.
- [ ] The fundamentals methods fetch both the statement data and whatever filing-date, accepted-date
      or period metadata FMP returns, preserved verbatim, since reconstructing first-known
      availability is the criterion this provider most needs tested on.
- [ ] All tests run against recorded or stubbed responses with no live API calls, CI fails if a
      test attempts network access, and the recorded fixtures are checked in with the date and
      endpoint they were captured from and with any key redacted.

## Technical notes
As with every adapter, `docs/ARCHITECTURE.md` restricts this layer to transport, auth and
pagination. FMP's responses are relatively flat and inviting to reshape; do not. Any tidying here
would remove exactly the evidence QNT-035's checks are looking for.

Two FMP-specific traps to handle at transport level without correcting: the API returns HTTP 200
with an error object or an empty array for many failure and not-entitled conditions, so status code
alone is not a success signal — detect the error shapes explicitly and map them onto the exception
taxonomy, distinguishing "not entitled at this tier" (a capability error) from "no such data" (an
empty but successful result), because scoring treats those very differently.

The second is that some FMP endpoints have historically served differing values for the same fact
across endpoints or between calls. Do not attempt to reconcile them in the adapter; fetch each
endpoint the checks need and store all of them, since inconsistency across repeated pulls is itself
a scored criterion (API reliability) and disagreement between endpoints is a finding worth
reporting.

Filing-date fields, where present, must be passed through untouched and unparsed. Their presence,
absence and plausibility are what QNT-035 measures, and a value silently normalised into a
timestamp here would make the measurement meaningless.

Symbol format is provider-specific (particularly for LSE and European listings). Mapping validation
universe identifiers to FMP symbols is transport-level work belonging here, but must be explicit,
testable, and recorded in request metadata so a wrong symbol is distinguishable from missing data.

Per-request metadata must include endpoint, parameters (key excluded), UTC fetch timestamp, and any
retry attempts, for the raw store (QNT-026) and the reliability criterion.

Development can proceed against recorded fixtures before a subscription exists; only the live
validation run is genuinely blocked.

## Dependencies
QNT-026 — the `MarketDataProvider` interface, exception taxonomy and raw store. QNT-028 — the
research report and the owner's subscription decision that supplies the API key and determines the
tier.

## Risks
**Expected BLOCKED-on-keys until the owner decision from QNT-028.** A paid API key is required for
any live run, so this ticket can be implemented and unit-tested against fixtures but cannot be
validated end to end until the subscription exists. Secondary risk: FMP's tier boundaries and
endpoint set have changed repeatedly, so recorded fixtures may go stale and capability declarations
may need revising after the first live run. Third: the HTTP-200-with-error pattern makes silent
partial data a real hazard, which is why error-shape detection is an acceptance criterion rather
than an implementation detail.

## Testing requirements
`tests/providers/test_fmp_adapter.py` using recorded/stubbed responses: byte-fidelity of stored
payloads, pagination, 429 and 5xx handling with backoff, HTTP-200-with-error-body mapping,
not-entitled versus empty-result discrimination, symbol mapping, and secret absence from logs
(including URLs) and files. No live calls in CI. No `timetravel` marker applies — the adapter
fetches rather than serving historical queries — but tests must assert that recorded fetch
timestamps are timezone-aware UTC, since downstream availability reasoning depends on them.

## Documentation requirements
A short adapter README or module docstring recording endpoints used, the tier assumed, observed
rate limits, and payload quirks discovered while implementing — this feeds QNT-036's report.
`docs/DATA_PROVIDER_EVALUATION.md` provider notes updated with anything the implementation reveals
that the desk research got wrong.

## Completion notes
_Not started._
