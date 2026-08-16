# QNT-077 — Screener and factor views

- **Ticket ID:** QNT-077
- **Status:** BACKLOG
- **Priority:** P3
- **Epic:** EPIC 13 — Research Terminal

## Problem
The screen is where most research begins, and where survivorship bias is easiest to reintroduce by
accident: a ranking that quietly uses today's universe, or a factor history chart drawn from
currently listed securities, will look entirely normal and be entirely wrong. The interface must make
the date and the universe of a ranking impossible to overlook.

## Objective
Build the screener and factor views: securities ranked by factor or composite within a universe on a
stated date, with factor scores and factor history displayed alongside their definition versions.

## Scope
A screener view (universe selector, as-of date selector, factor or composite selector, sortable and
filterable ranked table with pagination), a factor detail view (definition, version history, score
distribution, coverage), and a factor history chart for a selected security.

## Out of scope
Company detail (QNT-078); portfolio, risk and backtest views (QNT-079); editing factor definitions;
saved screens and alerting.

## Acceptance criteria
- [ ] The screener requires a universe and an as-of date, both always visible in the view, and the
      ranking is fetched with that date rather than defaulting to today implicitly.
- [ ] Displayed factor scores show the factor definition version, and changing the version changes
      the displayed scores rather than silently mixing versions in one table.
- [ ] Securities with missing factor scores are shown as missing and are excluded from ranking
      positions rather than being sorted to the bottom as zero.
- [ ] Factor history charts render gaps for periods with no data, and a security delisted before the
      selected date appears in a historical screen for an earlier date.
- [ ] Coverage — how many securities in the universe have a score — is displayed with every ranking.

## Technical notes
Coverage is a first-class number, not a diagnostic detail: a momentum screen covering 60% of the
universe is a different research object from one covering 98%, and the difference is invisible unless
displayed.

Sorting and filtering happen server-side through the API so the displayed ranking is the platform's
ranking; client-side sorting of a paginated table would produce a page-local ordering that looks
authoritative.

## Dependencies
QNT-076 — the terminal shell, API client and chart foundation.

## Risks
A fast, pleasant screener encourages exactly the specification-searching the methodology warns about;
mitigated by showing the as-of date and version prominently and by routing anything that becomes a
conclusion through the experiment registry rather than the screen.

## Testing requirements
Component tests for missing-score handling, version switching and required-parameter behaviour; an
end-to-end test against a fixture API asserting the ranking shown matches the ranking served.

## Documentation requirements
A short terminal usage note covering the as-of and version controls and the meaning of the coverage
figure.

## Completion notes
_Not started._
