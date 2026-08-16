# Roadmap

Milestones gate each other; see `VISION.md`. The backlog in `/tickets` is the executable form of
this roadmap — this file states ordering and intent only.

## M1 — Trustworthy historical data (current)

Question to answer: *can we reliably reconstruct historical UK equity data without survivorship
bias or future information?*

**Status 2026-08-16:** the machinery is code-complete and tested on fixtures — security
master (bitemporal), market-data schemas + adjustment engine, PIT fundamentals chain,
provider interface + raw store, validation universe, bake-off harness + pre-registered
scoring, universe engine. What remains is data-dependent and **blocked on the owner's
provider sign-off** (see DATA_PROVIDER_EVALUATION.md recommendation): adapters
(QNT-031…033), FTSE membership sourcing and the real-data survivorship gate
(QNT-039…041), and the empirical bake-off runs that produce the Results section.
M1's question can only be answered affirmatively once real provider data has flowed
through the whole chain.

Critical path:

1. Foundation: scaffold, tooling/CI, config/logging, docs, ticket system (QNT-001…005).
2. Security master: domain model, identifier maps with effective dates, storage, resolution,
   PIT lookups, lifecycle tests (QNT-006…012).
3. Provider interface + raw ingestion layer (QNT-026).
4. Market-data canonical schema, corporate actions, adjustment engine, calendars (QNT-013…019).
5. Fundamentals canonical schema with PIT fields and time-travel tests (QNT-020…025).
6. Bake-off: validation universe, provider research report (**owner decision: subscribe**),
   harness, adapters (EODHD/FMP/Tiingo), empirical checks, comparison report (QNT-027…036).
7. Universe engine: time-indexed membership, FTSE sourcing, survivorship tests (QNT-037…041).

Exit criteria: for the validation universe, we can reproduce as-traded and adjusted price
histories through splits/dividends/delistings, answer `members(universe, date)` historically,
and query fundamentals `as_of` any date with time-travel tests green — using the chosen
provider's real data.

## M2 — Factor research

Factor framework and momentum/quality/value sets (QNT-042…049), backtesting engine
(QNT-050…057), risk engine (QNT-058…062), experiment registry (QNT-063…066).

## M3 — Portfolio and access

Portfolio construction (QNT-067…071), research API (QNT-072…075), research terminal
(QNT-076…079), LLM interface (QNT-080…082).

## M4 — Execution

Paper trading (QNT-083…086); live trading with safeguards (QNT-087…090) only after paper
infrastructure is validated.
