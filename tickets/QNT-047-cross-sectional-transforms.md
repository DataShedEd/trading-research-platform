# QNT-047 — Cross-sectional transforms

- **Ticket ID:** QNT-047
- **Status:** DONE
- **Priority:** P2
- **Epic:** EPIC 7 — Factor Engine

## Problem
Raw factor values are not comparable across securities or across dates: earnings yield and momentum
live on different scales, outliers dominate any weighted combination, and a factor's cross-sectional
distribution shifts over time. Standardising ad hoc inside each consumer produces silent
inconsistencies, and an undocumented winsorisation threshold is a parameter that can be tuned until
results improve.

## Objective
Provide winsorisation, z-scoring, ranking with an explicit tie policy, and an optional
sector-neutralisation step as deterministic, tested transforms available to factor definitions and
composites.

## Scope
`src/trp/factors/transforms.py`: winsorisation by percentile or by standard deviations;
z-scoring (mean/standard-deviation and a robust median/MAD variant); ranking to percentile with a
declared tie policy; sector-neutralisation by demeaning or re-ranking within sector groups; a
documented policy for missing values and for groups too small to standardise. Each transform is
registered under the QNT-042 transform registry so definitions can name it.

## Out of scope
Factor definitions themselves (QNT-044, QNT-045, QNT-046); composite weighting (QNT-048); risk-model
style neutralisation against estimated exposures.

## Acceptance criteria
- [ ] Each transform is registered by identifier, parameterised by configuration, and produces
      identical output for identical input (deterministic, including tie handling).
- [ ] The tie policy for ranking is explicit and configurable, and a test with many equal values
      asserts the resulting percentile distribution matches the documented policy exactly.
- [ ] Winsorisation is applied cross-sectionally per date with configured thresholds, is
      order-independent with respect to the input row order, and its thresholds are recorded in the
      factor definition rather than defaulted silently.
- [ ] Missing values are excluded from the computation of distribution statistics and remain missing
      in the output — never imputed to zero or to the mean — and this is tested.
- [ ] Sector-neutralisation groups by the sector field available at the computation date and falls
      back to a documented behaviour when a group has fewer than a configured minimum number of
      securities.
- [ ] Behaviour on synthetic distributions is tested: normal, heavy-tailed, constant, single-member,
      and all-missing cross-sections.

## Technical notes
Transforms operate per date across the universe, so the universe used is part of the result — a
z-score is relative to whoever else was in the set. Callers must pass the universe explicitly rather
than standardising over whatever rows happen to be present.

Imputing missing factor values to the cross-sectional mean is a common convenience that quietly
assigns average rank to companies that failed to report; the conservative choice is to propagate
missingness and let the composite's missing-component policy (QNT-048) decide.

## Dependencies
QNT-042 — supplies the transform registry and configuration surface these plug into.

## Risks
Winsorisation thresholds are a tunable parameter with material effect on results; changing one after
seeing results is exactly the flattering choice RESEARCH_METHODOLOGY rule 8 requires documenting.
Mitigated by holding thresholds in versioned definitions so a change is a new version.

## Testing requirements
`tests/factors/test_transforms.py` — synthetic distributions (normal, heavy-tailed, constant,
single-member, all-missing); tie-policy assertions; row-order independence; missing-value
propagation; sector groups below the minimum size; robust versus standard z-score on an outlier
fixture.

No historical-data access is added by this ticket, so no time-travel test is required; the
transforms must, however, be exercised inside the QNT-049 suite as part of end-to-end factor
computation.

## Documentation requirements
Factor catalogue section documenting each transform, its parameters, its tie and missing-value
policies, and the requirement that the universe be passed explicitly.

## Completion notes
2026-08-21. `trp.factors.transforms`: winsorise (percentile-interpolated, thresholds
always from configuration — no silent default), zscore, zscore_robust (median/1.4826xMAD;
zero-MAD refused), rank_percentile ((rank-0.5)/n with average/min/max tie policies,
asserted exactly on a many-ties fixture), sector_neutralise (demean within groups from a
caller-supplied PIT sector mapping — no sector reference data ships yet; below
min_group_size or unmapped securities pass through UNNEUTRALISED with a warning, never
silently dropped or global-demeaned). All registered by identifier in a cross-sectional
registry that composite configurations name. Uniform policies, tested: only ok rows
touched; missing never imputed and excluded from statistics; deterministic and row-order
independent; degenerate cross-sections (constant/single-member/all-missing) typed. The
robust-vs-standard outlier fixture shows the point: a 1000x outlier hides inside its own
stdev under plain z (|z| < 2) and stands out >100 under median/MAD. 815 tests green.
