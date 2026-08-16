# QNT-058 — Exposure calculations

- **Ticket ID:** QNT-058
- **Status:** BACKLOG
- **Priority:** P2
- **Epic:** EPIC 9 — Risk Engine

## Problem
"What am I actually exposed to?" is the first question any portfolio raises, and it cannot be
answered from a list of positions alone. Weights depend on the valuation date and price source;
sector, country and currency exposures depend on classification data that changes over time; factor
exposures depend on factor definitions and their versions. Without one calculation shared by
backtests, paper portfolios and live portfolios, the same holdings will report different exposures
depending on which code path asked.

## Objective
Compute position weights and grouped exposures — sector, country, listing currency, and factor
exposures — for any portfolio snapshot, from a single implementation that does not know or care
whether the snapshot came from a simulation or a broker.

## Scope
New `trp.risk` package: a portfolio snapshot representation (positions, quantities, prices,
valuation timestamp, base currency, cash), weight calculation on market value, and grouped exposure
aggregation over security-master attributes and factor scores. Long, short, gross and net exposure.
Unit tests.

## Out of scope
Volatility, beta and correlation (QNT-059); drawdown, concentration and turnover (QNT-060); VaR and
scenarios (QNT-061); the unified interface and its adapters (QNT-062); any charting.

## Acceptance criteria
- [ ] Weights are computed from market value in the portfolio base currency and sum to 1 for a
      long-only fully invested portfolio; gross, net, long and short exposure are reported
      separately for a portfolio containing shorts.
- [ ] Sector, country and currency exposures are aggregated from time-indexed security-master
      attributes read `as_of` the snapshot date, never from current classifications.
- [ ] Factor exposures are reported as weighted average factor scores tagged with the factor
      definition version used.
- [ ] Securities missing a classification or factor score appear in an explicit `unclassified`
      bucket rather than being dropped, and the bucket weight is part of the returned result.
- [ ] Unit tests cover a long-only portfolio, a long/short portfolio, and a portfolio with a
      missing classification.

## Technical notes
Classification lookups take `as_of` like every other historical read (ARCHITECTURE). A company that
moved sector in 2018 must show its 2015 sector in a 2015 snapshot.

Exposure results should be plain typed structures (grouping key to weight) rather than dataframes at
the API boundary, so callers cannot silently reindex them. Cash is a first-class row, not an implied
residual — a portfolio holding 8% cash must report it.

## Dependencies
QNT-051 — supplies the portfolio and position state that exposures are computed from.

## Risks
Silently dropping unclassified securities makes exposures look tidier than reality and understates
concentration; mitigated by the explicit bucket. Using current classifications for historical
snapshots is a survivorship-flavoured bias and is prevented by the `as_of` requirement.

## Testing requirements
`tests/risk/test_exposures.py`, plus a `timetravel`-marked test asserting that a historical snapshot
does not pick up a classification change dated after the snapshot date.

## Documentation requirements
`docs/ARCHITECTURE.md` gains the `trp.risk` package in the layer diagram. Exposure definitions
(gross, net, unclassified handling) documented in the module docstring.

## Completion notes
_Not started._
