# QNT-040 — Broad UK-listed universe construction

- **Ticket ID:** QNT-040
- **Status:** BLOCKED
- **Priority:** P1
- **Epic:** EPIC 6 — Historical Universe Engine

## Problem
Index universes are narrow and depend on constituent history whose coverage is limited (QNT-039).
Most research questions need a broader opportunity set — all UK ordinary listings, including the
ones that no longer exist. Building that set from "securities currently listed" would be the purest
form of survivorship bias, and building it from an unfiltered security master would include shell
companies and untradeable microcaps whose prices make any strategy look good on paper.

## Objective
Construct a rules-based UK-listed universe from the security master — every UK ordinary listing
including delisted names — with size and liquidity filters computed strictly from data available at
each date, materialised into the QNT-037 membership schema.

## Scope
`src/trp/universe/sources/uk_broad.py` — a constructor that, for each date in a configured
rebalance schedule, selects securities meeting the rules and emits membership spells; the rule
configuration itself as a versioned configuration object (exchange and MIC set, security type,
currency, minimum market capitalisation, minimum median daily traded value, minimum price history,
optional price floor); and the materialisation job writing the resulting spells.

Base rules: ordinary shares (excluding ADRs, preference shares, investment-trust classes where
identified as such, and non-UK primary listings) on the London Stock Exchange main market and, as a
separately named universe, AIM. Delisted securities are included for the period they were listed
and satisfied the filters.

## Out of scope
Index constituent history (QNT-039); factor computation over the universe (Epic 7); sector
classification, beyond carrying whatever sector field the security master already supplies; the
acceptance suite (QNT-041).

## Acceptance criteria
- [ ] The constructed universe includes securities that have since delisted, for exactly the period
      during which they were listed and passed the filters, verified against named fixture
      companies rather than counts alone.
- [ ] Every filter input at a given membership date is computed only from data with
      `available_at`/trading date at or before that date — a test perturbs data dated after the
      membership date and asserts membership is unchanged.
- [ ] Filter rules are a versioned configuration object, and each emitted membership row's `source`
      identifies the rule set and its version; changing a threshold produces a new version rather
      than silently rewriting history under the same name.
- [ ] Rebuilding the universe from unchanged inputs produces identical membership spells
      (deterministic), and consecutive qualifying rebalance dates merge into a single spell rather
      than one row per date.
- [ ] Securities failing a filter at one rebalance date and passing at the next produce two disjoint
      spells, and the transition dates match the rebalance schedule.
- [ ] Universe size over time is reported, and the report is inspected for implausible
      discontinuities (for example a step change caused by data coverage rather than by market
      events).

## Technical notes
The point-in-time discipline lives in the filters, not just in the membership table. Market
capitalisation at date *t* must use the price on or before *t* and the shares outstanding known at
*t* — a share count restated later must not retroactively change 2012 membership. Median daily
traded value uses a trailing window ending at *t*, never centred or forward-looking.

A minimum trading history requirement (for example 126 trading days) both stabilises the liquidity
estimate and keeps IPOs out until they have traded, which is the conservative choice. Similarly, a
price floor guards against the microcap tick-size artefacts that produce enormous spurious returns;
whether to apply one, and at what level, is a documented choice per QUANT_PRINCIPLES §5 because it
materially affects results.

Rebalance the universe monthly or quarterly rather than daily: daily re-evaluation creates
membership churn at the filter boundary that shows up as phantom turnover in backtests. Emit spells
by grouping consecutive qualifying dates, which is why the rebalance schedule is part of the
configuration.

Keep main-market and AIM as separate named universes with a documented union universe rather than
one blended set — AIM's liquidity and disclosure characteristics differ enough that mixing them
silently would be a methodological choice hidden inside a universe name.

Currency handling: LSE quotes many securities in pence (`GBX`). Market-capitalisation thresholds
must be applied in a single normalised currency, using the quotation-unit information carried by
the listing record, or the filter will admit or exclude by a factor of one hundred.

## Dependencies
QNT-037 — supplies the membership schema the constructed spells are written into.
QNT-011 — supplies the point-in-time security master query API used to enumerate listings and their
status at each date.

## Risks
Filter thresholds are parameters, and parameters invite optimisation. A universe tuned until a
strategy works is data snooping wearing a universe's clothes. Mitigated by versioning rule sets, by
requiring the version in `source`, and by RESEARCH_METHODOLOGY rule 8 documentation of any change
made after results have been seen.

Data coverage is likely to be thinner for small and delisted companies, so the universe may thin
out in early years for reasons of data rather than market structure. Mitigated by the size-over-time
report and by documenting the effective usable start date.

## Testing requirements
`tests/universe/test_uk_broad_universe.py` — filter unit tests with synthetic securities at
threshold boundaries, spell merging across consecutive rebalance dates, spell splitting on a failed
intermediate date, `GBX`/`GBP` normalisation, and exclusion of non-ordinary security types.

`tests/timetravel/test_uk_broad_universe.py` (marker `timetravel`) — a fixture in which shares
outstanding are restated after the fact, and one in which a delisted company's later data is
absent, must both leave historical membership unchanged; a company that delisted in 2014 must
appear in membership for 2013 and be absent for 2015.

## Documentation requirements
`docs/DATA_MODEL.md` universes section listing the rules-based universe names. A universe
definition document (or a section in `docs/UNIVERSE_COVERAGE.md`) stating each rule, its threshold,
its version history, and the rationale for the conservative choices. `DECISIONS.md` entry for the
price floor and rebalance frequency choices.

## Completion notes
_Not started._

**BLOCKED (2026-08-16):** rule-based construction needs the security master populated with
real UK listings (post provider sign-off, QNT-028 gate).
