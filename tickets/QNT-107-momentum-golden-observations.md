# QNT-107 — 12-1 momentum: documented convention + golden observations

- **Ticket ID:** QNT-107
- **Status:** IN_PROGRESS
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
- [ ] Convention documented (docs/ or module docstring referenced from docs).
- [ ] ≥4 golden dates including a stressed period; ≥3 securities per date from top /
      middle / bottom of ranking, plus at least one non-OK status case.
- [ ] Independent reconstruction matches production to documented tolerance.
- [ ] Tests are permanent (default suite or gate) and human-readable enough to answer
      "why was X ranked #7?".

## Completion notes
_In progress._
