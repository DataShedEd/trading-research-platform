# QNT-044 — Momentum factor set

- **Ticket ID:** QNT-044
- **Status:** BACKLOG
- **Priority:** P2
- **Epic:** EPIC 7 — Factor Engine

## Problem
Momentum is the first signal any equity research programme reaches for, and it is easy to compute
subtly wrong: including the most recent month, using unadjusted prices across a split, or ranking on
a window that quietly extends past the observation date. Each error produces a plausible series and
a flattering backtest.

## Objective
Express a momentum factor set — 12-1, 6-1, 3-month, and volatility-adjusted momentum — as versioned
definitions in the QNT-042 framework, computed from the QNT-043 returns library, with values
validated against hand-computed fixtures.

## Scope
Definition files under `config/factors/momentum/` for each variant, plus any transform
implementations they need registered in `trp.factors`; the volatility-adjusted variant dividing
cumulative return by realised volatility of returns over the same window; fixtures and tests.

## Out of scope
Cross-sectional standardisation and ranking (QNT-047); composites (QNT-048); the returns library
itself (QNT-043); alternative momentum measures such as residual or earnings momentum.

## Acceptance criteria
- [ ] Four definitions exist as versioned configuration — 12-1, 6-1, 3-month, and
      volatility-adjusted — each naming its window, skip period, and return type explicitly, with no
      window parameters hard-coded in Python.
- [ ] Each factor's values match hand-computed fixtures to a documented tolerance, including a
      fixture spanning a split and one spanning a dividend.
- [ ] The skip period is honoured: a test asserts that a price move within the skipped month changes
      the 3-month factor but not the 12-1 factor.
- [ ] Securities with insufficient price history at the computation date return the "insufficient
      data" result from QNT-043 rather than a value computed from a shorter window.
- [ ] Volatility-adjusted momentum uses realised volatility computed over the same window from the
      same return series, and its behaviour at near-zero volatility is defined and tested.

## Technical notes
Total returns rather than price returns are the default for momentum; the choice is recorded in each
definition so an experiment can vary it. Realised volatility uses the standard deviation of daily
returns over the window, annualised by the documented convention.

Keep each variant a separate definition rather than one parameterised definition with defaults —
versioning is per definition, and an experiment must cite the exact variant it used.

## Dependencies
QNT-042 — supplies the definition framework, registry, and version tagging.
QNT-043 — supplies the return windows and skip-period semantics the definitions rest on.

## Risks
Momentum variants are cheap to generate, which invites searching over windows until one works.
Mitigated by RESEARCH_METHODOLOGY rule 3 (count the shots) and by keeping the shipped set small and
conventional rather than exhaustive.

## Testing requirements
`tests/factors/test_momentum.py` — hand-computed fixtures per variant; split and dividend fixtures;
skip-period assertion; insufficient-history handling; near-zero volatility behaviour.

`tests/timetravel/test_momentum_factors.py` (marker `timetravel`) — a factor value at date *t* must
be unchanged by prices dated after *t*, and unchanged by a corporate action announced after *t*.

## Documentation requirements
A factor catalogue entry per variant recording its definition, window, skip, return type, and
version history.

## Completion notes
_Not started._
