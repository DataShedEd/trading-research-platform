# QNT-109 — Future-data invariance per data class

- **Ticket ID:** QNT-109
- **Status:** DONE
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
- [x] Each of the five classes has a named test (or a documented pointer to the existing
      test covering it) asserting bit-identical results through T.
- [x] Tests marked `timetravel`, running in the default suite.

## Completion notes
`tests/timetravel/test_invariance_classes.py` — five per-class differential tests at the
backtest level, each asserting polars frame equality over daily ledger + event log +
rebalance record (the full persisted result):

- future price bars only;
- future corporate actions only (a future-dated split AND a late-published dividend);
- later lifecycle/security-master knowledge (a DelistingAction with available_at after
  T is inert — DEC-017's max(ex_date, knowable) rule);
- future universe membership (real UniverseQuery + write_universe; a spell recorded
  after T whose event-time covers the run is invisible; negative control verified —
  moving recorded_at before T changes the result, so the test bites);
- later fundamental observations (roe-scored strategy; a future filing and a
  restatement of an in-window period published after T are both inert; store genuinely
  drives selection — events non-empty asserted).

Identifier-resolution knowledge (ticker reuse, renames) is enforced upstream of the
engine and covered by tests/timetravel/test_security_master_pit.py and tests/lifecycle/;
this is documented in the module docstring rather than duplicated. No legitimate
bit-identity exceptions were needed — full frame equality holds for every class.
