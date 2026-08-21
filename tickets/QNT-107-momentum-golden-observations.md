# QNT-107 — 12-1 momentum: documented convention + golden observations

- **Ticket ID:** QNT-107
- **Status:** DONE
- **Priority:** P1
- **Epic:** EPIC 7 — Factor Engine
- **Depends on:** QNT-044 (DONE), QNT-049 (DONE)

## Problem
The 12-1 momentum implementation is tested for PIT invariance but not against
independently reconstructed values on the real dataset. "The production function agrees
with itself" is not validation. A human cannot currently answer "why was this security
ranked #7 on this date?" without reading source code.

## Objective
(1) The exact 12-1 convention documented in one place. (2) Golden cross-sections at
several historical dates — early, mid-period, stressed, recent — with securities from
different ranking regions reconstructed independently from canonical source data, and
persisted as data-driven regression tests.

## Scope
- Document the convention (calendar-month windows with skip, endpoint resolution,
  staleness, coverage floor, total-return reinvestment, delisting treatment).
- For each golden date: PIT FTSE 100 universe, full ranked cross-section, several
  securities re-derived by an INDEPENDENT simple implementation (direct canonical reads,
  no trp.factors machinery) showing: membership evidence, start/end bars, corporate
  actions in the window, computed return, rank, missing-data treatment.
- Persist expected values as fixtures; a test recomputes production values and asserts
  agreement with the independent reconstruction, not just self-consistency.

## Acceptance criteria
- [x] Convention documented (docs/ or module docstring referenced from docs).
- [x] ≥4 golden dates including a stressed period; ≥3 securities per date from top /
      middle / bottom of ranking, plus at least one non-OK status case.
- [x] Independent reconstruction matches production to documented tolerance.
- [x] Tests are permanent (default suite or gate) and human-readable enough to answer
      "why was X ranked #7?".

## Completion notes
- Convention documented in `tests/gate/test_momentum_golden_gate.py`'s module docstring
  and summarised in docs/RESEARCH_METHODOLOGY.md ("The 12-1 momentum convention"):
  calendar-month windows (never 21/252 observations), last-bar-on-or-before endpoints
  (≤15d stale), ex-date-reinvestment total return, 60% coverage floor, typed statuses.
- Golden dates 2011-06-30 / 2015-06-30 / 2020-03-31 (COVID) / 2025-06-30. Full 100-name
  PIT cross-sections pinned in tests/gate/golden/momentum_12_1_goldens.json; per date,
  top/middle/bottom names re-derived by an independent textbook implementation reading
  canonical parquet directly (formula in the docstring) — agreement to ~1e-15 relative
  everywhere (tolerance 1e-9). Non-OK cases behave as documented: Xstrata and SABMiller
  are DEC-016 no_data, M&G is insufficient_data (<12m post-IPO history). Fixture
  regeneration is deliberate only: `python tests/gate/test_momentum_golden_gate.py regen`.
- **CORRECTION (found by this ticket's inspection, §8 of the 2026-08-21 directive):**
  `trp.factors.materialise` passed NO corporate actions into factor computation, so the
  MATERIALISED panel's "total-return" momentum was dividend-free and exposed to
  unadjusted split gaps. The backtest path was always correct (it passes
  market.actions). Fixed by sharing the backtest's exact input-assembly rule
  (`trp.backtest.context.computable_inputs`, extracted so the two surfaces cannot
  diverge) and re-materialising momentum_12_1, momentum_12_1_vol_adjusted, momentum_3_0,
  momentum_6_1 and qvm_equal (1000 files). Quantified impact on the panel: mean value
  shift +2.57pp (median +2.79pp — the missing dividend yield), max |Δ| 23.3 (a split
  gap), 54 status changes of 20,000 rows; a hypothetical top-20 selection built off the
  OLD panel would have differed in ~180/200 months by ~2 names. Backtest results and
  all registered experiment metrics are UNAFFECTED. Before/after retained: defective
  files archived at data/derived/factors_pre_qnt107_correction/.
