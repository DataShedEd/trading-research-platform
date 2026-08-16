# QNT-076 — Research terminal application skeleton

- **Ticket ID:** QNT-076
- **Status:** BACKLOG
- **Priority:** P3
- **Epic:** EPIC 13 — Research Terminal

## Problem
A research interface is the most tempting thing to build and the least useful thing to build early:
charts make bad data look convincing, and effort spent on a terminal is effort not spent on the data
layer that determines whether anything shown in it is true. `VISION.md` is explicit that this work
does not start until the data layer is reliable. When it does start, it needs a shell that consumes
the research API only — a frontend that reaches into Parquet directly would fork the platform's query
semantics immediately.

## Objective
Create the web frontend skeleton: application scaffold, navigation shell, a typed API client
generated from or checked against the OpenAPI schema, and a charting foundation, with no domain views
yet.

## Scope
A separate frontend application (Next.js or React with Vite — the choice is made and recorded in this
ticket) in its own directory: build tooling, TypeScript configuration, linting, navigation shell,
typed API client, a Plotly-based chart wrapper with shared defaults, loading and error states, and
its own CI job.

## Out of scope
All domain views (QNT-077, QNT-078, QNT-079); authentication; server-side rendering of research data;
mobile layouts; any direct data-layer access from the frontend.

## Acceptance criteria
- [ ] The application builds, lints and type-checks in CI as a separate job, and the commands are
      documented alongside the existing Python commands.
- [ ] All data access goes through a generated or schema-checked API client; a test or lint rule fails
      the build if a component issues an unchecked request, and the frontend has no data-layer
      dependency.
- [ ] The navigation shell renders placeholder routes for screener, company, portfolio and backtest
      views, with consistent loading, empty and error states available to all of them.
- [ ] The chart wrapper establishes shared defaults (axis formatting, date handling in UTC, colour
      usage, missing-data rendering) and renders a time series from live API data in a smoke test.
- [ ] The framework choice is recorded in `docs/DECISIONS.md` with alternatives and consequences.

## Technical notes
Missing data must render as a gap, never as a connected line between the points either side of it —
an interpolated chart of a suspended security is a lie told by a default setting. That belongs in the
shared wrapper so no individual view can get it wrong.

Dates on the wire are UTC (ARCHITECTURE); the terminal displays market-local dates for calendar
concepts and must not shift a period end by a timezone offset.

## Dependencies
QNT-073 — the data endpoints the client consumes and the schema it is generated from.

## Risks
Frontend work expanding to fill available time while research capability stalls; mitigated by the
milestone gating in `VISION.md` and by keeping this ticket to a shell with no domain logic.

## Testing requirements
Component tests for the shell and its states, a smoke test rendering a chart from a running API, and
the build/lint/type-check job green in CI.

## Documentation requirements
`docs/DECISIONS.md` entry for the framework choice; `docs/ARCHITECTURE.md` records the
API-only-access rule for the frontend; run instructions in CLAUDE.md.

## Completion notes
_Not started._
