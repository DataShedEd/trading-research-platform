# QNT-099 — First registered experiment: QVM composite vs momentum

- **Ticket ID:** QNT-099
- **Status:** DONE
- **Priority:** P1
- **Epic:** EPIC 10 — Research Experiment Registry

## Problem
The registry, the factor library and the backtest engine are each complete and tested, but
no research has yet flowed through the full discipline: hypothesis written first, runs
captured with manifests, conclusion citing evidence with weaknesses on record.

## Objective
Register and run the platform's first hypothesis end-to-end: does the pre-registered
equal-thirds quality-value-momentum composite improve on 12-1 momentum alone, net of
pessimistic costs, on the survivorship-free FTSE 100 over the DEC-014 window?

## Scope
Registry wiring for composite factors in backtests (fundamentals/fx/shares roots through
the clock-bound context); one hypothesis; two confirmatory experiments under it
(momentum baseline, qvm_equal candidate — identical construction: monthly, top 20, equal
weight, shipped costs, ISF benchmark); runs via the automatic manifest capture from a
clean tree; tearsheets; a concluded record with judgement, evidence citation and
weaknesses.

## Acceptance criteria
- [x] Both runs recorded reproducible (clean tree) with full manifests.
- [x] Comparison table across the two experiments from the registry.
- [x] A conclusion with an explicit judgement, the evidence run cited, weaknesses
      recorded, and the variant count stamped.

## Completion notes
2026-08-21. HYP-769cd965: equal-thirds QVM beats 12-1 momentum alone on risk-adjusted
excess return, identical construction. Two confirmatory experiments (momentum-baseline,
qvm-equal-candidate), each run TWICE: the first attempt's candidate run was refused as
confirmatory evidence by the registry itself — the executor wrote a tracked tearsheet
mid-run, dirtying the tree for the next manifest capture — precisely the failure mode
QNT-064 exists to catch; tearsheets now live inside the immutable run record and the
clean re-runs (r2) are flagged reproducible and reproduced r1 metric-for-metric (21/21
both). Evidence: same net CAGR (10.92% vs 10.90%), volatility 17.8% vs 19.2%, tracking
error 8.9% vs 12.2%, Sharpe 0.596 vs 0.562, IR 0.363 vs 0.283 — but max drawdown
WORSENED to -44.3% from -37.8%. Concluded SUPPORTED on the stated risk-adjusted claim
with the drawdown refutation recorded as the first weakness, six weaknesses total,
three follow-ups (sub-period IR, drawdown attribution, rule-4 sensitivity —
parameter_sensitivity marked not-yet-run), variant count 2, no multiple-testing warning.
Registry, manifests, comparison and workflow all exercised end-to-end on real research.
