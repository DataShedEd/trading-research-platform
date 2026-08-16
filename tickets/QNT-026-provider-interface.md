# QNT-026 — Common provider interface and raw ingestion layer

- **Ticket ID:** QNT-026
- **Status:** DONE
- **Priority:** P1
- **Epic:** EPIC 5 — Data Provider Bake-Off

## Problem
Without a common interface, each provider's quirks leak into canonical transforms and the bake-off
compares implementations rather than data. And without a raw layer, every API response is consumed
once and thrown away: when a canonical value is later found to be wrong there is no way to tell
whether the provider sent it that way or we mangled it, and re-deriving history means paying for
and re-fetching data that may no longer be available on the same terms. Both problems get
dramatically more expensive after adapters exist, so the interface and the raw layer come first.

## Objective
Define the abstract `MarketDataProvider` interface that every adapter implements, and the raw
ingestion layer that stores provider payloads verbatim, immutably and append-only, under
`data/raw/<provider>/`.

## Scope
`src/trp/providers/base.py` — the abstract interface with methods `securities`, `prices`,
`corporate_actions`, `fundamentals`, `financial_periods` and `delisted_securities`, plus the
provider-identity metadata (name, version, capability flags) each adapter declares.
`src/trp/ingestion/raw.py` — a `RawStore` writing payloads with fetch timestamp, endpoint,
parameter hash and provider identity, plus a reader for reprocessing. A fake in-memory provider in
`tests/fakes/` usable by every later ticket. Unit tests.

## Out of scope
Any real provider adapter (QNT-031…033); semantic normalisation of any kind — adapters and the raw
layer translate transport only; the canonical transforms that consume raw payloads (Epics 3 and 4);
the bake-off runner (QNT-029).

## Acceptance criteria
- [x] `MarketDataProvider` is an abstract base class with the six methods named above, fully typed
      under `mypy --strict`, each documented with its parameters, its return shape and whether it
      is expected to be paginated; a subclass that omits a method fails to instantiate.
- [x] Capability declaration is explicit: an adapter states which methods it genuinely supports, so
      an unsupported dataset raises a distinguishable `ProviderCapabilityError` rather than
      returning an empty result that the bake-off would score as "no data found".
- [x] Raw payloads are written verbatim — bytes as received, with no reformatting, key reordering,
      type coercion or pretty-printing — alongside sidecar metadata recording provider, endpoint,
      request parameters, a stable hash of those parameters, fetch timestamp (UTC) and the
      adapter/provider version.
- [x] The raw store is append-only and immutable: writing the same endpoint and parameters again
      creates a new timestamped record rather than overwriting, and there is no public delete or
      overwrite method; a test asserts an existing payload file is never modified.
- [x] Credentials never reach disk or logs: the parameter hash and stored metadata exclude API keys
      and tokens, and a test asserts a known secret value is absent from every written file and
      from captured log output.
- [x] A fake in-memory provider implements the full interface with scriptable responses, errors,
      pagination and rate-limit conditions, and the full ingestion path is exercised against it in
      tests with no network access.

## Technical notes
`docs/ARCHITECTURE.md` fixes the layering: `trp.providers` handles transport, auth and pagination
only; `trp.ingestion` writes verbatim to `data/raw/<provider>/…`; `trp.canonical` does all semantic
work. The interface must therefore return provider-shaped data, not canonical domain models —
resisting the temptation to normalise inside an adapter is the whole point, because raw fidelity is
what makes reprocessing and the bake-off's evidence trail possible.

Method signatures may be refined during implementation; what must not change is that every method
takes an explicit date range or as-at parameter where the underlying data is historical, and that
none of them returns "the current view" implicitly. Fundamentals in particular should surface
whatever announcement or filing timestamps the provider offers, untouched, so QNT-035 can measure
their presence and QNT-020's `available_at` can be derived honestly rather than guessed.

Raw layout should be navigable by a human: provider, dataset kind, security or batch identifier,
and fetch date in the path, with the payload's original content type preserved. Compression is fine
provided the decompressed bytes are identical. Note that licensing may forbid retaining some
payloads (`docs/ARCHITECTURE.md`); the store should support a documented per-provider retention
policy flag, with the default being retain.

Rate limiting and retry belong to adapters, but the interface should define the exception types
(`ProviderRateLimitError`, `ProviderUnavailableError`, `ProviderCapabilityError`) so the harness in
QNT-029 can distinguish "provider says no such data" from "we were throttled" — a distinction that
materially changes a bake-off score.

Settings and credentials come from `trp.config` (QNT-003) via `load_settings()` at entry points,
never at import time, and API keys stay `SecretStr` throughout.

## Dependencies
QNT-003 — settings for data-layer paths and provider credentials, and logging conventions.

## Risks
An interface shaped around the first provider implemented tends to fit only that provider, which
would bias the bake-off. Mitigated by writing the interface before any real adapter and validating
it against the desk research in QNT-028 as adapters land — a signature change is cheap now and
expensive after three adapters exist. A second risk is accidental secret leakage into the raw
store, which is why it is an explicit acceptance criterion.

## Testing requirements
`tests/providers/test_interface.py` for abstractness, capability errors and typing;
`tests/ingestion/test_raw_store.py` for verbatim fidelity (byte comparison), metadata contents,
append-only behaviour, parameter hashing stability, and secret absence. All tests run against the
fake provider with no live network calls, and CI must fail if a test attempts one. No `timetravel`
marker is required — the raw layer stores payloads rather than answering historical queries — but
tests must assert that fetch timestamps are timezone-aware UTC so downstream availability reasoning
has a trustworthy base.

## Documentation requirements
`docs/ARCHITECTURE.md` provider/ingestion sections updated with the final method list, the
exception taxonomy and the raw path layout. `CLAUDE.md` gains a note that adapters must never
normalise and that raw payloads are never edited or deleted.

## Completion notes
2026-08-16. `src/trp/providers/base.py`: `MarketDataProvider` ABC (six methods, each
yielding `RawPayload` pages — pagination is the iterator shape), class-level
`name`/`version`/`capabilities` with `require()` raising `ProviderCapabilityError`;
exception taxonomy `ProviderError` / `ProviderCapabilityError` / `ProviderRateLimitError`
(carries retry-after) / `ProviderUnavailableError`. `src/trp/ingestion/raw.py`: `RawStore`
with human-navigable layout `data/raw/<provider>/<dataset>/<params_hash>/<stamp>-<n>.<ext>`
+ `.meta.json` sidecars (`RawRecord`), append-only (sequence suffix, no delete/overwrite
method), verbatim byte fidelity tested against deliberately non-JSON bytes, UTC-aware fetch
timestamps enforced, order-independent parameter hashing, credential denylist stripping
before hash/write (tested: secret absent from every file), and per-write `retain=False`
storing sidecar + content SHA only for licence-restricted payloads. `tests/fakes/provider.py`:
scriptable `FakeProvider` (pages, mid-pagination errors, rate limits, call log) +
`NoFundamentalsProvider`; full ingestion path exercised with no network. Docs: ARCHITECTURE
provider/ingestion sections rewritten with the final contract; CLAUDE.md notes the
never-normalise / never-delete rules. All checks green (127 tests).
