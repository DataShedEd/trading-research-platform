# QNT-030 — Scoring rubric and criteria weights

- **Ticket ID:** QNT-030
- **Status:** BACKLOG
- **Priority:** P1
- **Epic:** EPIC 5 — Data Provider Bake-Off

## Problem
The harness produces hundreds of individual check results per provider, which is far too much
detail to make a decision from and far too easy to summarise dishonestly. Counting passes treats a
missing delisted company — which invalidates the entire survivorship-bias guarantee — as equal to a
slow endpoint. Worse, if weights are chosen after the results are seen, the rubric becomes a
rationalisation of a preference rather than a decision procedure, and nothing in the report can be
trusted.

## Objective
Encode the criteria table in `docs/DATA_PROVIDER_EVALUATION.md` as weighted scoring functions —
with delisted coverage and point-in-time fundamental availability weighted highest — producing an
aggregate score per provider alongside a per-criterion breakdown, with the weights fixed and
committed before any real provider results exist.

## Scope
`src/trp/bakeoff/scoring.py`: a criterion registry mapping each criterion to the checks that
inform it and a scoring function from check results to a normalised per-criterion score; the weight
table as versioned data; aggregation to a per-provider total with a full breakdown; handling of
not-applicable and missing results. Unit tests using synthetic check results.

## Out of scope
The checks themselves (QNT-034, QNT-035); the harness (QNT-029); rendering the scores into the
document (QNT-036); the purchase decision, which is the owner's and is informed by, not made by,
the score.

## Acceptance criteria
- [ ] Every criterion in the `docs/DATA_PROVIDER_EVALUATION.md` table — historical depth, delisted
      coverage, corporate-action accuracy, identifier stability, PIT fundamental availability,
      revision history, API reliability, rate limits and bulk, licensing, cost — has a scoring
      function and a weight, and the weights live in a versioned data file rather than as literals
      in code.
- [ ] Delisted coverage and PIT fundamental availability carry the highest weights, and the
      rationale for the full weight ordering is documented alongside the table.
- [ ] Per-criterion scores are normalised to a common scale so that criteria measured by different
      numbers of checks are comparable, and the aggregate is a transparent weighted sum whose
      per-criterion contributions are exposed in the breakdown, not just the total.
- [ ] Not-applicable results are excluded from a criterion's denominator rather than counted as
      passes or failures, and a criterion with no applicable results scores as `unmeasured`
      (propagated into the report) rather than as zero or as full marks.
- [ ] A provider missing an entire dataset kind — because the tier does not include it or the
      adapter declares no capability — scores zero on the criteria that depend on it, with the
      reason recorded, and this is distinguishable from having been tested and failed.
- [ ] Unit tests over synthetic check results cover: a perfect provider, a provider failing only
      the highest-weighted criteria (which must rank below one failing several low-weighted ones),
      not-applicable handling, unmeasured criteria, and weight-file validation rejecting weights
      that do not sum as documented.

## Technical notes
The weights are a judgement about what this platform is for, so state the reasoning in the
document, not just the numbers. Delisted coverage and PIT availability dominate because
QUANT_PRINCIPLES §1 and §2 are non-negotiable: a provider failing either cannot support correct
research at any price, whereas a provider with poor rate limits is merely inconvenient. Consider
whether those two should be near-vetoes rather than merely heavy weights — a documented minimum
threshold below which a provider is marked unsuitable regardless of total — and if so, implement
the threshold explicitly rather than by weight inflation.

Fixing the weights before results exist is the guard against post-hoc rationalisation, and mirrors
the pre-registration discipline QUANT_PRINCIPLES §5 asks for in research. Version the weight file
so that if the weights are later revised, previously published scores remain attributable to the
version that produced them, and any revision is visible in a diff with its own justification.

Cost and licensing are not measured by API checks; they come from QNT-028's research. Model them as
criteria whose inputs are declared facts rather than check results, keeping the same score shape so
the aggregation is uniform — and make it obvious in the breakdown which criteria are empirical and
which are declared, since they carry different evidential weight.

Scores are ordinal, not cardinal: a total of 0.82 versus 0.79 is not a meaningful difference, and
the report should not present it as one. Expose the breakdown prominently and consider emitting a
confidence or coverage indicator (how many checks actually ran) alongside each criterion, so a
score computed from three checks is not read like one computed from forty.

Use `Decimal` for weights and scores to keep the arithmetic exact and reproducible (DEC-005); this
also avoids the irritation of floating-point noise making two identical runs differ in the last
digit of a published table.

## Dependencies
QNT-029 — the `CheckResult` structure and result persistence that scoring consumes.

## Risks
A rubric can be gamed unintentionally: if one criterion is measured by many more checks than
another, normalisation choices quietly change the ranking. Mitigated by explicit normalisation,
the coverage indicator, and tests asserting the intended ordering on synthetic inputs. The larger
risk is treating the aggregate score as the decision; mitigated by presenting the breakdown as the
primary output and keeping the purchase decision explicitly with the owner (QNT-028).

## Testing requirements
`tests/bakeoff/test_scoring.py` built entirely on synthetic `CheckResult` fixtures — no harness run
and no provider involved. Cover each criterion's scoring function individually, the aggregation,
the ordering assertions in the acceptance criteria, weight-file schema validation and versioning,
and determinism (the same inputs produce byte-identical scores). No `timetravel` marker applies;
scoring reads bake-off results, not historical market data.

## Documentation requirements
`docs/DATA_PROVIDER_EVALUATION.md` scoring-criteria table extended with the weight for each
criterion, whether it is empirical or declared, and the rationale for the ordering; a note that
weights were fixed before results were collected, with the weight-file version recorded. A
`DECISIONS.md` entry if a veto threshold is adopted, since that can disqualify a provider outright.

## Completion notes
_Not started._
