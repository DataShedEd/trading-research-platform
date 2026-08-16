# QNT-069 — Constraint framework

- **Ticket ID:** QNT-069
- **Status:** BACKLOG
- **Priority:** P3
- **Epic:** EPIC 11 — Portfolio Construction

## Problem
Constraints are how a research portfolio becomes a portfolio anyone would actually run: no more than
X% in one name, no more than Y% in one sector, no more than Z% turnover per rebalance. They are also
where implementations get sloppy — capping a weight and renormalising quietly breaks another cap, and
an infeasible constraint set silently returns *something* rather than saying it cannot be done. An
unreported constraint violation in a backtest is a result for a portfolio that could not have been
held.

## Objective
Provide declarative constraints — position caps, sector caps, turnover limits — applied
deterministically to a weight vector, with feasibility checked and infeasibility reported rather
than approximated.

## Scope
`trp.portfolio.constraints`: constraint definitions, a deterministic application procedure
(iterative capping with redistribution, converging or failing within a bounded number of passes),
feasibility checking before application, and a structured infeasibility report naming the conflicting
constraints.

## Out of scope
Optimisation-based constraint satisfaction (QNT-070); constraints requiring integer decisions such
as minimum lot sizes; regulatory constraints; per-order limits, which are execution-side (QNT-088).

## Acceptance criteria
- [ ] Constraints are declarative objects; adding a new constraint type does not modify the
      application procedure's control flow.
- [ ] Application is deterministic and idempotent: applying it twice yields identical weights, and
      the same inputs always produce the same output regardless of input ordering.
- [ ] After application, all constraints are satisfied simultaneously and weights still sum to 1;
      redistribution after capping never breaks a previously satisfied cap.
- [ ] An infeasible constraint set (for example a 5% position cap over 10 securities) raises with a
      report naming the conflicting constraints and the shortfall, and never returns a
      best-effort weight vector.
- [ ] A binding constraint is reported in the result even when application succeeds, so backtests can
      show how often constraints changed the portfolio.

## Technical notes
Iterative capping with redistribution needs an explicit convergence bound; if it has not converged
within the bound, that is an infeasibility report, not a silent exit with the current iterate.

Turnover constraints differ from the others in that they depend on the previous portfolio, so
constraint application needs the prior weights as an input. A turnover cap that cannot be met while
satisfying position caps is a genuine infeasibility and must be reported as such rather than resolved
by preferring one constraint over the other — unless the caller states a priority order explicitly.

## Dependencies
QNT-067 — the weight vectors constraints are applied to.

## Risks
Silent constraint relaxation is the failure that invalidates results; mitigated by the
simultaneous-satisfaction acceptance criterion and by property tests in QNT-071 that assert it over
generated inputs rather than a handful of examples.

## Testing requirements
`tests/portfolio/test_constraints.py`: simultaneous satisfaction, idempotence, ordering independence,
turnover constraints against a prior portfolio, and infeasibility reporting.

## Documentation requirements
Constraint semantics, the redistribution procedure and the priority-order rule documented in the
module docstring.

## Completion notes
_Not started._
