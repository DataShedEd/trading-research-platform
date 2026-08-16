# QNT-051 — Portfolio accounting

- **Ticket ID:** QNT-051
- **Status:** BACKLOG
- **Priority:** P2
- **Epic:** EPIC 8 — Backtesting Engine

## Problem
Backtest accounting errors are silent and directional. A position in a company that delists simply
disappears from most naive implementations, which is equivalent to selling it at its last price
before the collapse — the single largest source of overstated returns in equity backtests. Dividends
credited to nobody, or splits applied to price but not to share count, produce the same kind of
quiet, favourable drift.

## Objective
Implement the portfolio ledger — positions, cash, dividends received, corporate-action pass-through,
and explicit delisting handling — with accounting identities asserted at every step.

## Scope
`src/trp/backtest/portfolio.py`: a `Portfolio` holding share quantities per `security_id` and a cash
balance; trade application; daily mark-to-market using raw prices with corporate actions applied as
events; dividend crediting on pay date (or ex-date under a documented convention); split and
consolidation adjustment of share counts; rights-issue treatment where data permits; and delisting
resolution — proceeds credited where known, written off to zero where the company failed, never a
silent removal.

## Out of scope
Rebalancing rules and target weights (QNT-052); transaction costs (QNT-053); metrics (QNT-054);
margin, shorting, and leverage.

## Acceptance criteria
- [ ] The accounting identity holds after every event: portfolio value equals cash plus the sum of
      position quantities times their marked prices, asserted on every simulated day in tests.
- [ ] Cash is conserved: total cash change over a period equals dividends received plus sale
      proceeds minus purchase costs, with no unexplained residual.
- [ ] A delisting event resolves the position explicitly — proceeds credited to cash where the
      corporate-action record supplies terms, written off to zero where it records failure — and a
      test asserts that no code path removes a position without a corresponding cash entry or
      write-off.
- [ ] Dividends on held positions are credited with the documented timing convention and appear in
      the event log with their `security_id`, amount, and currency.
- [ ] Splits and consolidations adjust share quantity so that position value is unchanged across
      the ex-date, verified against a hand-computed fixture.
- [ ] Every ledger change is recorded in an append-only event log sufficient to reconstruct the
      portfolio state on any simulated day.

## Technical notes
Hold quantities and mark with raw as-traded prices, applying corporate actions as explicit events,
rather than marking with adjusted prices — adjusted prices already embed the actions, and mixing the
two double-counts. This also makes the dividend cash flow visible instead of hidden inside a total
return.

Write-off versus proceeds is a data question the corporate-action record answers; where it does not,
the conservative default is a write-off to zero, documented in the run record per
QUANT_PRINCIPLES §5.

## Dependencies
QNT-050 — supplies the simulation clock, event loop, and point-in-time context the ledger runs under.

## Risks
Fractional shares and rounding can accumulate small biases over decades of rebalances. Mitigated by
choosing and documenting a share-rounding convention and asserting the cash identity to a fixed
tolerance.

## Testing requirements
`tests/backtest/test_portfolio.py` — accounting and cash identities across a multi-event fixture;
hand-computed split, consolidation, ordinary dividend and special dividend cases; delisting with
proceeds and delisting as failure; event-log reconstruction.

`tests/timetravel/test_portfolio_accounting.py` (marker `timetravel`) — corporate actions with an
`available_at` after the simulated date must not affect the portfolio on that date; a delisting
recorded later must not retroactively alter earlier valuations.

## Documentation requirements
`docs/DATA_MODEL.md` or the backtest documentation recording the ledger schema, the dividend timing
convention, the share-rounding convention, and the delisting resolution rules.

## Completion notes
_Not started._
