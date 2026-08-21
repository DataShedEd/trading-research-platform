# QNT-045 — Quality factor set

- **Ticket ID:** QNT-045
- **Status:** DONE
- **Priority:** P2
- **Epic:** EPIC 7 — Factor Engine

## Problem
Quality metrics are computed from fundamentals, which are the most look-ahead-prone data in the
platform: a figure for the year ending December is not knowable in January, restatements change
history, and a naive join on period end date puts next year's profitability into this year's
ranking. Quality factors computed that way are the single most flattering error available.

## Objective
Express a quality factor set — ROIC, ROE, gross profitability, operating margin, free-cash-flow
margin, leverage, accruals, and earnings stability — as versioned definitions, each computed only
from fundamentals available at the computation date.

## Scope
Definition files under `config/factors/quality/` and the transforms they require; a shared
fundamentals-assembly helper that fetches the latest fundamentals available at `as_of` for a
security and exposes the line items each definition needs; handling of negative and zero
denominators; fixtures and tests.

Definitions: ROIC (NOPAT over invested capital), ROE, gross profitability (gross profit over total
assets), operating margin, FCF margin, leverage (net debt to equity and to EBITDA), accruals
(the difference between earnings and cash flow, scaled), and earnings stability (variability of
earnings over a trailing window).

## Out of scope
The fundamentals store and its point-in-time API (QNT-025); cross-sectional standardisation
(QNT-047); composites (QNT-048); sector-specific adjustments beyond documenting where a metric is
not meaningful.

## Acceptance criteria
- [ ] Each of the eight metrics exists as a versioned definition naming its line items, period type,
      and scaling, with no line-item mapping hard-coded in Python.
- [ ] Every definition resolves fundamentals through the `available_at` filter, and a test asserts a
      value computed at a date before a report's availability uses the prior report, not the newer
      one.
- [ ] Restatements are respected: a value computed as at a date between original filing and
      restatement uses the original figures, verified by fixture.
- [ ] Negative, zero, and missing denominators produce a documented result — typed "not meaningful"
      rather than an infinity, a `NaN`, or a silently clipped number — and each case is tested.
- [ ] Earnings stability is computed over an explicit trailing window of reported periods with a
      minimum-periods requirement, and securities below it return "insufficient data".
- [ ] Values are validated against hand-computed fixtures built from a small synthetic set of
      financial statements.

## Technical notes
Balance-sheet items are point-in-time stocks and income-statement items are flows; ratios mixing
the two should use average balances over the period where the convention calls for it, and the
choice must be stated in the definition rather than assumed.

Financial-sector securities make leverage and several margin metrics meaningless. The honest
treatment is to return "not meaningful" by sector rather than a number nobody should rank on;
whether such securities are excluded from a universe is a universe decision, not a factor one.

## Dependencies
QNT-042 — supplies the definition framework and version tagging.
QNT-025 — supplies the point-in-time fundamentals with `available_at` and restatement history.

## Risks
Line-item normalisation across providers is imperfect; a definition mapped to the wrong normalised
name yields a plausible but meaningless factor. Mitigated by hand-computed fixtures and by failing
loudly on missing line items rather than substituting zero.

## Testing requirements
`tests/factors/test_quality.py` — hand-computed fixtures per metric; negative-equity, zero-revenue
and missing-line-item cases; averaging convention; earnings-stability minimum periods.

`tests/timetravel/test_quality_factors.py` (marker `timetravel`) — a factor at date *t* uses the
most recent report with `available_at <= t`; adding a later filing or a restatement to the fixture
leaves the value at *t* unchanged while changing it at a later date.

## Documentation requirements
Factor catalogue entries recording each metric's formula, line items, period convention, and
not-meaningful rules.

## Completion notes
2026-08-21. Nine v1 definitions under config/factors/quality/ (roe, gross_profitability,
operating_margin, fcf_margin, cash_conversion — inverse Sloan accruals oriented
higher-is-better — earnings_stability, net_debt_to_equity, net_debt_to_ebitda, roic),
line items entirely in configuration via three generic transforms in
`trp.factors.fundamental`: `fundamental_ratio` (sum/sum with numerator_minus and a
positive-denominator refusal), `earnings_stability` (trailing-window CV, min-periods
typed), `roic` (effective tax from tax_expense/pre_tax_profit clamped [0,1], zero shield
when pre-tax <= 0; invested = equity + net_debt). Consistent-snapshot rule stated once:
each security's latest period holding every required item, period-end balances, mixed
currencies refused. ComputeContext gained fundamentals_root/fx_root; everything resolves
through the QNT-025 as-of choke point. Required four taxonomy additions (v1.1: ebit,
ebitda, tax_expense, net_debt) and six mapping promotions (v1.2), each evidenced against
the 197-payload corpus. Hand fixtures for all nine (ROIC 160/700 etc.); refusals typed
and tested (negative equity, negative EBITDA, missing items, <4 years); the two QNT-045
acceptance PIT cases (pre-availability uses the prior report; restatement respected
between filings) plus the timetravel suite. DEVIATION, documented in the catalogue: the
by-sector not-meaningful rule for financials cannot be applied — no sector reference
data exists yet; composites must not lean on leverage/margins across financials until it
does. Real FTSE 100 cross-section (2020-06-30, gate-tested): 98-100/100 computable,
medians ROE 15.2% / gross profitability 19.3% / ROIC 12.0%. 797 default + 21 gate green.
