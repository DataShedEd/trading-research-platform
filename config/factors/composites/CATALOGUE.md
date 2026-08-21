# Composite catalogue (QNT-048)

One pre-registered composite, deliberately (RESEARCH_METHODOLOGY rule 3: variants are
countable; a new blend or weight is a new versioned definition, never an edit).

## qvm_equal v1
Momentum (momentum_12_1), value (earnings_yield) and quality (gross_profitability) in
equal thirds — three well-evidenced, weakly correlated premia with no tuned weights.
Each component is winsorised at [1, 99] then robust-z-scored (median/MAD) across the
computation universe before weighting; missing components renormalise with at least two
required. Scores carry a `components` column naming every component version.

## Conventions (all composites)
- Standardisation is REQUIRED: weights over raw scales are meaningless.
- Missing policies: `drop` / `renormalise` (+ min_components) / `neutral`. Neutral awards
  a standardised zero for an unreported metric — systematically kind to the incomplete —
  and choosing it is visible in the definition.
- Directions: -1 flips lower-is-better components (the leverage pair) at the definition.
- No composite may be hard-coded: a repository test fails if any registry factor name
  appears in `src/trp/factors` source.
- Materialised scores: `uv run python -m trp.factors.materialise` writes monthly
  cross-sections (FTSE 100, DEC-014 window) to `data/derived/factors/`, queryable via the
  `factor_values` view (SQL console / DataGrip after `make db`).
