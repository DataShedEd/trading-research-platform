# QNT-048 — Composite factor scoring

- **Ticket ID:** QNT-048
- **Status:** DONE
- **Priority:** P2
- **Epic:** EPIC 7 — Factor Engine

## Problem
A strategy usually ranks securities on a blend of signals, and the blend is the most tempting place
in the system to hide assumptions. A composite hard-coded in Python fixes the weights permanently,
makes the weighting impossible to vary as an experimental parameter, and leaves the treatment of a
missing component — a company with no book value, say — as whatever the arithmetic happened to do.

## Objective
Provide configurable weighted composites over versioned factor components, with an explicit
missing-component policy, and with no permanent hard-coded composite anywhere in the codebase.

## Scope
`src/trp/factors/composite.py` plus composite definition files under `config/factors/composites/`:
component references by factor name *and* version, weights, the standardisation transform applied to
each component before combination, and the missing-component policy (drop the security, renormalise
the remaining weights, or treat the component as neutral — chosen per composite, not globally).
Composite values are written to the derived store tagged with the composite version and every
component version.

## Out of scope
Component factor definitions (QNT-044, QNT-045, QNT-046); the transforms themselves (QNT-047);
portfolio construction and weighting (QNT-052); the acceptance suite (QNT-049).

## Acceptance criteria
- [ ] A composite is defined entirely in configuration — components by name and version, weights,
      per-component transform, missing policy — and loading validates that every referenced
      component version exists in the registry.
- [ ] Composite values are persisted tagged with the composite version and the versions of all
      components, so a stored score identifies exactly the definitions that produced it.
- [ ] The missing-component policy is explicit per composite and tested for each supported option,
      including that renormalisation reweights the remaining components to sum to the original
      total.
- [ ] A minimum-components requirement is enforced: a security missing more than the configured
      number of components yields no composite score rather than a score built from one input.
- [ ] A repository check (test or lint rule) asserts no hard-coded composite exists in
      `src/trp/factors/` — weights appear only in configuration.
- [ ] Composite values match hand-computed fixtures for a two- and a three-component composite,
      including a case exercising the missing policy.

## Technical notes
Components must be standardised before weighting or the weights are meaningless — a weight of 0.5 on
a raw earnings yield and 0.5 on a raw momentum is not an equal blend. The per-component transform
reference is therefore required, not optional.

Treating a missing component as neutral (zero z-score) is not a safe default: it awards median rank
to a company for a metric it could not report, which systematically favours the incomplete. Where a
composite chooses it, that choice is visible in its configuration and in its version.

## Dependencies
QNT-044, QNT-045, QNT-046 — supply the component factors a composite references by version.
QNT-047 — supplies the standardisation transforms applied to components before weighting.

## Risks
Composite weights are the easiest parameters to over-optimise, and a search over weights is a search
over hypotheses. Mitigated by versioning every composite so the number of variants tried is countable
per RESEARCH_METHODOLOGY rule 3, and by the sensitivity reporting required by rule 4.

## Testing requirements
`tests/factors/test_composite.py` — hand-computed fixtures; each missing-component policy;
renormalisation arithmetic; minimum-components enforcement; rejection of a definition referencing an
unknown component version; the no-hard-coded-composite repository check.

`tests/timetravel/test_composite_scoring.py` (marker `timetravel`) — a composite score at date *t*
is unchanged by any data dated after *t*, and changes only through its components when information
available at *t* changes.

## Documentation requirements
Factor catalogue section for composites, documenting the configuration schema, the missing-component
policies and their implications, and the rule that no composite may be hard-coded.

## Completion notes
2026-08-21. `trp.factors.composite`: the `composite` transform — components by name AND
version with weights and per-component direction (+1/-1 for lower-is-better), REQUIRED
standardisation from the QNT-047 registry, optional winsorise pre-step, explicit missing
policy (drop / renormalise with min_components / neutral — the unsafe one, visible in
config). Registry load validates every referenced component version exists and rejects
nested composites; every emitted row carries a `components` column (name@version list).
Hand fixtures cover the weighted two-component case and each policy (renormalisation
arithmetic asserted to the z-score). The no-hard-coding repository test forbids any
registry factor name in src/trp/factors source (transform-identifier names exempted).
One shipped composite: qvm_equal v1 (equal thirds momentum_12_1 / earnings_yield /
gross_profitability, winsorise [1,99] + robust z, renormalise min 2) — catalogued with
the shot-counting rationale. NEW `trp.factors.materialise` persists monthly cross-sections
(FTSE 100, 2010->) through the never-overwrite writer; qvm_equal is materialised for all
200 month-ends and queryable via the factor_values view (SQL console/DataGrip).
Timetravel: scores invariant to future bars and future filings; a knowable restatement
genuinely moves them. 815 default + 21 gate tests green.
