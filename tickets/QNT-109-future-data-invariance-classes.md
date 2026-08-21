# QNT-109 — Future-data invariance per data class

- **Ticket ID:** QNT-109
- **Status:** IN_PROGRESS
- **Priority:** P1
- **Epic:** EPIC 8 — Backtesting Engine
- **Depends on:** QNT-057 (DONE)

## Problem
The flagship invariance test extends the store with future bars and late-announced
actions in one combined check. The directive requires the concept per data class: a
historical experiment through T must be bit-identical when the dataset later gains
(a) future price bars, (b) future corporate actions, (c) later security-master
knowledge, (d) future universe membership information, (e) later fundamental
observations/revisions — each proven separately so a regression names its class.

## Objective
One explicit bit-identical invariance test per applicable data class at the backtest
level, permanent in the timetravel suite.

## Scope
- Audit existing coverage (test_backtest_leakage, test_factor_point_in_time,
  test_momentum_factors, security-master/universe PIT tests) and map each class.
- Add missing classes as separate differential tests: baseline run vs run on the
  extended store, asserting frame equality (bit-identical daily ledger + events).
- Where bit-identity is impossible for a legitimate reason, document why and use the
  strongest deterministic equivalence available.

## Acceptance criteria
- [ ] Each of the five classes has a named test (or a documented pointer to the existing
      test covering it) asserting bit-identical results through T.
- [ ] Tests marked `timetravel`, running in the default suite.

## Completion notes
_In progress._
