# QNT-072 — FastAPI application skeleton

- **Ticket ID:** QNT-072
- **Status:** BACKLOG
- **Priority:** P3
- **Epic:** EPIC 12 — Research API

## Problem
The research terminal, the LLM interface and any ad-hoc tooling all need the same access to the
platform's data and calculations. Without one HTTP surface they will each import `trp` directly and
grow their own subtly different query logic, and the platform's correctness guarantees — `as_of` on
every historical read, versioned factor definitions — will be re-implemented several times and
weakened each time.

## Objective
Stand up the `trp.api` FastAPI application: app factory, configuration wiring, health endpoint,
consistent error handling and OpenAPI documentation, read-only by design.

## Scope
`src/trp/api/`: app factory taking `Settings`, dependency wiring for data access, health endpoint
reporting service and data-layer status, structured error responses, request logging with a
correlation identifier, OpenAPI metadata, and a local development entry point.

## Out of scope
All domain endpoints (QNT-073, QNT-074, QNT-075); authentication beyond binding to localhost;
any write or mutating endpoint; deployment, containerisation and TLS.

## Acceptance criteria
- [ ] `create_app(settings)` returns a configured application with no import-time settings access,
      matching the QNT-003 configuration convention.
- [ ] The health endpoint reports application status and whether the canonical data layer is
      readable, and returns a non-200 status when it is not.
- [ ] All errors return a consistent structured body (code, message, correlation id) with no stack
      traces or filesystem paths in responses; an unhandled exception is logged with its correlation
      id and returns a generic 500.
- [ ] OpenAPI documentation is generated and served, and every endpoint has a summary and response
      model.
- [ ] The application defines no route with a method other than GET at this stage, asserted by a
      test that enumerates the route table.

## Technical notes
Read-only by design is a deliberate constraint, not an unfinished state: the API is a window onto
research data, and anything that mutates state (experiment records, orders) goes through the code
paths that own it. The route-table test makes accidental drift visible.

Bind to localhost by default. This is a single-user personal platform (VISION) and authentication is
not a substitute for not being reachable; if that ever changes, it becomes its own ticket rather
than a quiet configuration change.

## Dependencies
QNT-003 — typed settings and logging the application is wired from.

## Risks
An API skeleton invites premature endpoint proliferation ahead of the data layer being trustworthy;
mitigated by the milestone gating in `VISION.md` and by this ticket adding no domain routes.

## Testing requirements
`tests/api/test_app.py`: app factory construction, health endpoint in healthy and degraded states,
error-response shape, absence of stack traces in responses, and the GET-only route-table assertion.

## Documentation requirements
`docs/ARCHITECTURE.md` gains the `trp.api` package and the read-only, localhost-by-default stance.
Local run instructions added to CLAUDE.md commands.

## Completion notes
_Not started._
