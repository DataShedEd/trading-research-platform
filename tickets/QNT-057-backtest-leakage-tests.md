# QNT-057 — Backtest correctness and leakage regression suite

- **Ticket ID:** QNT-057
- **Status:** DONE
- **Priority:** P2
- **Epic:** EPIC 8 — Backtesting Engine

## Problem
The backtester composes the universe engine, the factor engine, the ledger, the cost model and the
metrics. Each is tested in isolation, but the errors that matter most — a delisted holding that
vanishes, a dividend credited twice, a restatement that rewrites a completed backtest — live in the
seams between them. A backtest with any of these defects runs to completion and returns a number
that looks like evidence.

## Objective
Build the end-to-end scenario and leakage regression suite for the backtester, and adopt it as the
acceptance gate for Epic 8: the epic is not complete until every scenario passes.

## Scope
`tests/timetravel/test_backtest_leakage.py` and `tests/backtest/test_scenarios.py` with a shared
synthetic canonical store. Scenarios, each with hand-computed expected outcomes:

- **Delisting mid-backtest** — a held security delists; proceeds or write-off flow through the
  ledger, the position does not persist, and the resulting return matches the hand computation.
- **Dividend during holding** — an ordinary and a special dividend on a held position are credited
  once each, with the documented timing.
- **Split during holding** — share count and position value behave correctly across the ex-date, and
  the return series shows no artificial jump.
- **Restatement mid-backtest** — a fundamental figure is restated during the simulated period;
  factor values and holdings before the restatement's `available_at` are unaffected, and only
  subsequent rebalances change.
- **As-of monotonicity** — moving the run's `as_of` forward is the only change that alters results;
  adding data dated after the run's end changes nothing.
- **Negative control** — a deliberately leaky engine variant (resolving the universe from current
  membership, or trading at the signal-generating close) fails identifiable scenarios.

## Out of scope
Universe survivorship testing (QNT-041) and factor point-in-time testing (QNT-049), both of which
this suite assumes are passing; performance benchmarking; statistical validation of results.

## Acceptance criteria
- [x] Scenarios have end-to-end tests with paper-derived expectations (dividends once-each,
      consolidation no-jump, delisting proceeds and total loss, round-trip turnover/costs).
      The restatement scenario uses a late-published corporate action — the restatement
      class that exists today; the fundamentals variant joins when fundamental factors are
      wired into the backtest (Epic 7 value/quality).
- [x] An as-of monotonicity test asserts that re-running an identical configuration against a data
      store extended with later-dated data produces byte-identical results.
- [x] A negative-control leaky engine fails at least three scenarios, proving the suite detects
      look-ahead and survivorship defects.
- [x] A reproducibility test asserts that a run reconstructed from its persisted `BacktestConfig`,
      data versions, and seed reproduces the original metrics exactly.
- [x] Costs, turnover and metrics are reconciled end-to-end within each scenario: gross return minus
      costs equals net return, and cumulative costs equal the ledger's cost debits.
- [x] The suite runs under the `timetravel` marker in CI on every change to `trp.backtest`, and Epic
      8 completion is recorded as gated on it passing.

## Technical notes
Build the scenarios on a small synthetic store with a handful of securities and a short simulated
period, so every expected value can genuinely be computed by hand and checked by a reader. A
scenario whose expected outcome came from running the code is a change detector, not a correctness
test.

The as-of monotonicity property is the strongest single statement the platform can make about its
own integrity: results are a function of information available at the simulated dates, and of
nothing else. Express it differentially — run against the restricted store, run against the extended
store, assert equality — so it needs no expected values at all.

## Dependencies
QNT-052 — supplies the rebalancing and weighting behaviour the scenarios exercise.
QNT-053 — supplies the cost model whose debits the reconciliations check.
QNT-054 — supplies the metrics the scenarios assert on.

## Risks
Synthetic fixtures may not reproduce the awkwardness of real provider data, so a leak triggered only
by real-world quirks could pass. Mitigated by a real-data smoke run under a separate marker that
skips cleanly when the canonical store is absent, and by requiring it for the epic gate.

The opposite risk is scenarios weakened over time to keep CI green; the negative control is the
guard against a suite that has quietly stopped asserting anything.

## Testing requirements
This ticket is itself the testing deliverable: `tests/backtest/test_scenarios.py` for the
hand-computed scenarios and `tests/timetravel/test_backtest_leakage.py` (marker `timetravel`) for
the monotonicity and restatement properties, plus a negative-control module verifying the leaky
engine variant is detected. CI must run the `timetravel` marker as a required check, and failures
must name the scenario, the simulated date, and the offending security.

## Documentation requirements
`docs/QUANT_PRINCIPLES.md` §1 and §3 cross-referenced to this suite as the backtest-layer
enforcement mechanism. `docs/RESEARCH_METHODOLOGY.md` note that no experiment may be recorded from a
backtest configuration whose scenarios are not covered here. Epic 8 documentation recording the
acceptance gate and the scenario list.

## Completion notes
2026-08-18. Epic 8's acceptance gate. `tests/backtest/test_scenarios.py`: five end-to-end
scenarios on a flat-price world built so every expectation is exact on paper (dividends
credited once each at ex-date; 1-for-2 consolidation with value 999,900 on every single
day; merger proceeds +20,000/999,900; failure write-off -100,000/999,900; round-trip
turnover 5% per leg) — each reconciles costs DIFFERENTIALLY: a zero-cost run of the
identical world differs by exactly the ledger's cost debits, and reported per-rebalance
costs equal those debits. `tests/timetravel/test_backtest_leakage.py`: as-of monotonicity
expressed with no expected values (extended store -> byte-identical daily/events/
rebalances) and the restatement property (a dividend published mid-run leaves every value
and event before its available_at identical, then genuinely changes the May rebalance).
`tests/backtest/test_negative_control.py`: `SameDayClockEngine` (via the extracted
`_decision_clock` hook) fails the execution-price scenario (buys 11,111 not 10,000) and
the knowledge-timing scenario (trades a month early on a same-morning announcement);
`FinalMembershipUniverse` fails the survivorship scenario (dodges exactly the 500,000
write-off) — three failing scenarios across two leak classes. Real-data gate
(`tests/gate/test_backtest_reproduction_gate.py`): the latest persisted run record
re-runs from its config.json alone and matches daily/events byte-for-byte (~29s).
CI runs timetravel in the default suite (addopts excludes only `gate`).
QUANT_PRINCIPLES §1/§3 and RESEARCH_METHODOLOGY rule 2 cross-referenced. 761 default +
8 gate tests green. EPIC 8 core chain (QNT-050..057) complete.
