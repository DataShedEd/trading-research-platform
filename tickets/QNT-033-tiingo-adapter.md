# QNT-033 — Tiingo provider adapter

- **Ticket ID:** QNT-033
- **Status:** DONE
- **Priority:** P1
- **Epic:** EPIC 5 — Data Provider Bake-Off

## Problem
Tiingo is the candidate with the strongest reputation for clean, well-adjusted end-of-day price
data at low cost, and the weakest expected coverage of the things this platform depends on:
non-US listings, delisted securities, and point-in-time fundamentals. That combination makes it the
most useful control in the bake-off — if it wins on price accuracy and loses on coverage, the
rubric's weighting is doing its job. Establishing either half of that requires an adapter, since
the evaluation refuses to score providers on advertised capability.

## Objective
Implement `MarketDataProvider` for Tiingo — EOD prices, splits and dividends, fundamentals, and
delisted-security lists — handling transport, authentication, pagination and rate limits only, with
no semantic normalisation whatsoever.

## Scope
`src/trp/providers/adapters/tiingo.py`: the adapter class, its capability declaration, endpoint
mapping for the six interface methods, authentication via `Settings` (`SecretStr`), pagination and
retry/backoff, mapping of HTTP and API error conditions onto the shared exception taxonomy, and the
per-request metadata the raw store needs. Recorded/stub response fixtures and tests.

## Out of scope
Any normalisation, renaming, unit conversion or type coercion of payload contents — that belongs to
`trp.canonical` (QNT-021 for fundamentals, Epic 3 for market data); the checks that judge the data
(QNT-034, QNT-035); scoring (QNT-030); purchasing the subscription (owner decision, QNT-028).

## Acceptance criteria
- [x] The adapter implements every `MarketDataProvider` method or explicitly declares the
      capability unsupported, with the declaration reflecting the subscribed tier rather than the
      full published product range; unsupported datasets raise `ProviderCapabilityError` rather
      than returning empty results.
- [x] Payloads reach the raw store byte-identical to the API response: no JSON re-serialisation, no
      key reordering, no numeric parsing on the way through; a test compares stored bytes with the
      recorded fixture exactly.
- [x] Authentication uses the API token from `Settings` as a `SecretStr`, sent as a header rather
      than a query parameter where the API permits, and the token appears in no log line, no
      exception message, no stored request metadata and no test artefact — asserted by a test using
      a known sentinel token value.
- [x] Pagination, rate limiting and transient errors are handled in the adapter: paged endpoints
      are followed to completion, HTTP 429 and the provider's hourly/daily quota responses raise
      `ProviderRateLimitError`, 5xx and timeouts retry with bounded exponential backoff, and
      persistent failure raises `ProviderUnavailableError` rather than returning partial data
      silently.
- [x] Both raw (as-traded) and provider-adjusted price fields are fetched and stored where the API
      returns them, kept distinguishable exactly as received, since raw-versus-adjusted consistency
      is one of the checks in QNT-034 and Tiingo's adjustment quality is the main reason it is in
      the bake-off.
- [x] All tests run against recorded or stubbed responses with no live API calls, CI fails if a
      test attempts network access, and the recorded fixtures are checked in with the date and
      endpoint they were captured from and with any token redacted.

## Technical notes
`docs/ARCHITECTURE.md` restricts adapters to transport, auth and pagination; that applies here even
though Tiingo's payloads are the tidiest of the three candidates and would be the least trouble to
map. Storing them verbatim keeps the comparison fair — the check layer must see what each provider
actually sent.

Capability declaration matters more for Tiingo than for the other adapters, because coverage gaps
are the expected finding. An honest `ProviderCapabilityError` for a dataset the tier does not
include produces a correct, explainable zero in the rubric; an empty list would be scored as "the
security does not exist", which is a different and unfair conclusion. Where a dataset exists but
only for US listings, declare the capability with its market scope rather than as a blanket yes.

Tiingo returns both unadjusted and adjusted OHLC alongside split and dividend factors in the same
records. Pass all of it through untouched — including the adjustment factors, which QNT-034 can
check against the validation universe's known split ratios without a second endpoint call.

Validation-universe securities outside the US may simply not resolve. Treat a genuine "no such
symbol" as a successful empty result distinct from an error, and record the symbol form attempted
in request metadata, so the identifier-stability and coverage criteria can distinguish a missing
security from a bad symbol guess.

Per-request metadata must include endpoint, parameters (token excluded), UTC fetch timestamp, and
any retry attempts, for the raw store (QNT-026) and the reliability criterion.

Development can proceed against recorded fixtures before a subscription exists; a free tier may
allow limited live validation earlier than for the other adapters, which is worth exploiting to
shake out the harness (QNT-029) against a real API sooner.

## Dependencies
QNT-026 — the `MarketDataProvider` interface, exception taxonomy and raw store. QNT-028 — the
research report and the owner's subscription decision that supplies the API token and determines
the tier.

## Risks
**Expected BLOCKED-on-keys until the owner decision from QNT-028**, though Tiingo's free tier may
partially unblock development earlier than for EODHD or FMP. Secondary risk: fundamentals and
non-US coverage may be thin enough that several interface methods are declared unsupported, which
is a legitimate bake-off result but must not be mistaken for an incomplete implementation — record
the declarations and their reasons explicitly. Third: fixtures recorded from a free tier may not
represent paid-tier response shapes or coverage.

## Testing requirements
`tests/providers/test_tiingo_adapter.py` using recorded/stubbed responses: byte-fidelity of stored
payloads, pagination, 429 and 5xx handling with backoff, capability errors with market scope,
raw-versus-adjusted fields both preserved, empty-result versus error discrimination, and token
absence from logs and files. No live calls in CI. No `timetravel` marker applies — the adapter
fetches rather than serving historical queries — but tests must assert that recorded fetch
timestamps are timezone-aware UTC, since downstream availability reasoning depends on them.

## Documentation requirements
A short adapter README or module docstring recording endpoints used, the tier assumed, observed
rate limits, market coverage actually available, and payload quirks discovered while implementing —
this feeds QNT-036's report. `docs/DATA_PROVIDER_EVALUATION.md` provider notes updated with
anything the implementation reveals that the desk research got wrong.

## Completion notes
2026-08-16. `src/trp/providers/adapters/tiingo.py` + shared `_http.py`. Tier: Starter
(free). Capabilities: prices, corporate actions (the daily series — Tiingo carries
`divCash`/`splitFactor` inline; documented), fundamentals (DOW-30 on free tier);
securities, financial_periods and delisted_securities declared unsupported with reasons
(no delisted endpoint exists — the coverage gap that makes Tiingo the US cross-check, as
this ticket's Problem predicted). Header auth (`Authorization: Token`), token hygiene
tested with a sentinel. Payload parsers extended additively for the dialect (top-level
arrays, splitFactor/divCash inference) per the neutral-convention plan. **Validated live**
(run `tiingo-final-1`): 18 cells; capability zeros surfaced honestly (9 unsupported
cells); Citigroup fundamentals 4xx (non-DOW entitlement) surfaced as provider_error;
found a genuine data-quality artefact — Apple's 2014 split stored as 7.000007, outside
exact-ratio tolerance; adjusted-vs-raw consistency passed 3/3 (Tiingo's reputed strength,
confirmed). Tests: `tests/providers/test_adapters.py`.

**BLOCKED (2026-08-16):** Tiingo Starter is free but still requires an account/API key the owner
must create. Per QNT-028, Tiingo serves as a US cross-check only (no LSE coverage); do not buy Power.
