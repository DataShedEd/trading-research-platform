# QNT-005 — Ticket system and initial backlog

- **Ticket ID:** QNT-005
- **Status:** DONE
- **Priority:** P1
- **Epic:** EPIC 1 — Project Foundation

## Problem
Without a repository-resident backlog, project state depends on chat history, which is not
durable memory.

## Objective
Complete ticket system: one markdown file per ticket using the standard template, ~90 tickets
covering all 16 epics, and `tickets/INDEX.md` as the human-readable source of truth.

## Scope
Ticket template; QNT-001…QNT-090 ticket files; INDEX.md grouped by epic with status/priority;
statuses BACKLOG/READY/IN_PROGRESS/BLOCKED/DONE; Milestone 1 critical path identified.

## Out of scope
Executing any other ticket.

## Acceptance criteria
- [x] Every epic from the brief has tickets; ~60–100 total.
- [x] Each ticket has all template sections (ID, title, status, priority, epic, problem,
      objective, scope, out of scope, acceptance criteria, technical notes, dependencies, risks,
      testing requirements, documentation requirements, completion notes).
- [x] INDEX.md lists every ticket with status and marks the M1 critical path.
- [x] Dependencies form a DAG consistent with the roadmap.

## Technical notes
Single QNT-NNN sequence across epics (DEC-006). Tickets for later epics are intentionally
lighter on technical notes — they will be refined when their epic approaches.

## Dependencies
QNT-004 (docs the tickets reference).

## Risks
Backlog rot — mitigated by the working rule that status changes are part of every ticket's work.

## Testing requirements
None (markdown), beyond INDEX consistency review.

## Documentation requirements
Workflow documented in CLAUDE.md.

## Completion notes
2026-08-16. 90 tickets created (QNT-001…QNT-090) across 16 epics; M1 path: QNT-006…QNT-041.
Commit `QNT-005`.
