# QNT-004 — Documentation suite

- **Ticket ID:** QNT-004
- **Status:** DONE
- **Priority:** P1
- **Epic:** EPIC 1 — Project Foundation

## Problem
The repository must be the durable project memory; without written vision, principles, and a
decision log, architectural knowledge lives only in conversations.

## Objective
All eight core documents exist with substantive content: VISION, ARCHITECTURE, DATA_MODEL,
QUANT_PRINCIPLES, DECISIONS, ROADMAP, RESEARCH_METHODOLOGY, DATA_PROVIDER_EVALUATION.

## Scope
Initial authoritative content reflecting the programme brief and decisions DEC-001…DEC-007.

## Out of scope
Generated sections of DATA_PROVIDER_EVALUATION (filled by QNT-028/QNT-036); per-epic design docs.

## Acceptance criteria
- [x] Eight documents present with real content (no placeholders except explicitly generated
      sections).
- [x] DECISIONS.md seeded with DEC-001…DEC-007 in the required structure.
- [x] QUANT_PRINCIPLES states PIT, survivorship, corporate-action, and reproducibility rules
      exactly as binding constraints.

## Technical notes
DATA_MODEL is conceptual; `trp.domain` code is authoritative once written.

## Dependencies
QNT-001.

## Risks
Docs drifting from code — mitigated by ticket workflow requiring doc updates per ticket.

## Testing requirements
None (prose).

## Documentation requirements
Self-referential.

## Completion notes
2026-08-16. Includes DEC-007 (conservative `available_at` imputation policy). Commit `QNT-004`.
