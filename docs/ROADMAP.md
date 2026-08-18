# Roadmap

Milestones gate each other; see `VISION.md`. The backlog in `/tickets` is the executable form of
this roadmap — this file states ordering and intent only.

## M1 — Trustworthy historical data (current)

Question to answer: *can we reliably reconstruct historical UK equity data without survivorship
bias or future information?*

**Status 2026-08-18: MILESTONE 1 COMPLETE.** The survivorship gate (QNT-041,
`uv run pytest -m gate`) is green on the real dataset: `members("FTSE100", date, as_of)`
answers correctly on every monthly date 2010–2026 with delisted members intact, every
member inside DEC-014 coverage has price data (DEC-016's 17 adjudicated gaps ≈2.5% of
member-months excepted, list may only shrink), and 1.26m canonical bars + 9.6k corporate
actions back the universe. Remaining under this milestone's epics: QNT-032 (FMP adapter,
BLOCKED by choice — likely never needed) and FTSE 250/350 sourcing (future, same
machinery). M1's question is answered: yes, from 2010 onwards, with enumerated exceptions.

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
