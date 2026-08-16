# QNT-078 — Company detail view

- **Ticket ID:** QNT-078
- **Status:** BACKLOG
- **Priority:** P3
- **Epic:** EPIC 13 — Research Terminal

## Problem
When a screen surfaces a security, the next question is always "why, and is it real?". Answering it
means looking at the price history with its corporate actions marked, the financial history as it was
reported, and the factor breakdown behind the ranking. Presented carelessly this view is a machine
for producing false impressions: an adjusted price chart with an unmarked 10-for-1 split looks like a
crash, and restated financials shown as a smooth history hide the revision that would have changed
the decision.

## Objective
Build a company detail view showing price history with corporate actions annotated, reported and
restated financial history, factor breakdown, and the signal explanation for the security.

## Scope
A per-security view: price chart with adjustment-mode toggle and corporate-action markers (splits,
dividends, rights issues, delisting); identifier and listing history; financial statement history
with an as-reported versus restated toggle; factor score breakdown with contributions; the signal
explanation payload rendered as a table.

## Out of scope
Prose explanation generation (QNT-081); news, filings or any data source not in the platform;
peer comparison; portfolio and backtest views (QNT-079).

## Acceptance criteria
- [ ] The price chart states its adjustment mode, offers as-traded and adjusted, and marks splits,
      dividends and delisting on the series; a split in the fixture data is visibly annotated in both
      modes.
- [ ] The financial history distinguishes as-reported from restated figures, showing the
      `available_at` date for each value and marking values whose availability was imputed (DEC-007).
- [ ] The factor breakdown shows each contributing factor, its score, its definition version and its
      contribution to the composite, and the contributions reconcile to the composite score shown.
- [ ] The view renders correctly for a delisted security, showing the delisting date and terminating
      the price series rather than displaying a flat line to the present.
- [ ] Identifier history (ticker changes with effective dates) is shown, resolved against the
      selected as-of date.

## Technical notes
The as-reported versus restated toggle is the visual form of the point-in-time principle and is the
single most valuable element of this view: it lets a researcher see what was actually knowable at a
past date rather than what is known now. It reads the same `as_of` fundamentals endpoint the
backtests use, so a discrepancy between chart and backtest indicates a real bug rather than a
presentation difference.

Corporate-action markers come from canonical corporate-action records, never from detecting jumps in
the price series.

## Dependencies
QNT-076 — the terminal shell, API client and chart foundation.

## Risks
A chart that silently interpolates over a suspension or misses a rights issue creates confident wrong
conclusions; mitigated by the shared gap-rendering rule from QNT-076 and by sourcing markers from
corporate-action data.

## Testing requirements
Component tests using a fixture security with a split, a dividend, a ticker change and a delisting;
assertions that markers appear in both adjustment modes, that the restated toggle changes values, and
that factor contributions sum to the displayed composite.

## Documentation requirements
Terminal usage note explaining the adjustment-mode and as-reported toggles and what the imputed-
availability marker means.

## Completion notes
_Not started._
