# QNT-029 — Bake-off harness core

- **Ticket ID:** QNT-029
- **Status:** DONE
- **Priority:** P1
- **Epic:** EPIC 5 — Data Provider Bake-Off

## Problem
Comparing three providers across a validation universe and four dataset kinds by hand is both
tedious and untrustworthy: results end up in a spreadsheet nobody can regenerate, checks get run
against one provider and not another, and the evidence behind a conclusion evaporates. Since the
output of this epic is a purchasing decision and a dependency the entire platform inherits, the
comparison has to be reproducible from persisted artefacts — the same standard QUANT_PRINCIPLES §4
applies to research results.

## Objective
Build the harness that drives the bake-off: for each (provider adapter × validation-universe
security × dataset kind) it fetches via the common interface, persists the raw payload, runs the
registered checks, and persists structured per-check results with evidence for the report
generator.

## Scope
`src/trp/bakeoff/harness.py` — the runner and its execution plan; `src/trp/bakeoff/checks.py` — the
check protocol and registry (`CheckResult` with pass/fail/not-applicable/error, evidence, and a
pointer to the raw payload that produced it); `src/trp/bakeoff/results.py` — structured result
persistence under `data/derived/bakeoff/` with a run identifier; a CLI entry point to execute a run
or a subset; tests against the fake provider from QNT-026.

## Out of scope
Scoring and weighting (QNT-030); the specific corporate-action and fundamental checks (QNT-034,
QNT-035) — this ticket ships the protocol and one or two trivial reference checks only; report
generation (QNT-036); real adapters (QNT-031…033).

## Acceptance criteria
- [x] The runner enumerates the full (provider × security × dataset kind) matrix from the QNT-027
      universe, supports running a subset by provider, market, awkward property or dataset kind,
      and records the universe version and provider/adapter versions in the run metadata.
- [x] Every fetch persists its raw payload through the QNT-026 raw store before any check runs, and
      each `CheckResult` references the raw record that produced it, so any result in the report
      can be traced to the bytes it came from.
- [x] Checks are registered against dataset kinds through a documented protocol, so QNT-034 and
      QNT-035 add checks without modifying the runner; a check declares which dataset kinds and
      which awkward properties it applies to.
- [x] Failure is isolated and informative: a provider error, a rate limit, an unsupported
      capability and a genuinely absent record produce four distinguishable outcomes, one failing
      check never aborts the run, and an exception inside a check is captured as an `error` result
      with its traceback rather than crashing the harness.
- [x] Results persist in a structured, machine-readable form keyed by run identifier, provider,
      security, dataset kind and check, with timestamps, so a run is fully reconstructible and two
      runs are comparable; re-running a completed run does not overwrite the previous run's results.
- [x] The whole harness runs end to end against the fake provider in tests — full matrix, checks,
      persistence and subset selection — with no network access, and rate-limit backoff behaviour
      is exercised via the fake.

## Technical notes
`docs/ARCHITECTURE.md` places this in `trp.bakeoff`; keep it a thin orchestrator over the provider
interface, the raw store and the check registry, since all the domain judgement lives in the checks
and the universe. Resist letting the harness normalise anything: checks read raw payloads (or an
adapter's lightly-typed transport-level output) because part of what is being measured is what the
provider actually sends.

Persisting raw before checking is the ordering that makes the epic honest — a check that fails must
be adjudicable months later without re-fetching, especially since a subscription may have lapsed by
then. It also means checks can be re-run over stored payloads without spending API quota; support
that explicitly with a replay mode reading from the raw store instead of the network, and make it
the default when a matching payload already exists for the run.

Rate limits are the practical constraint on a real run. Expect per-minute and per-day caps that
differ per provider (QNT-028's research supplies them); implement conservative pacing plus backoff
on `ProviderRateLimitError`, make a run resumable so a day-cap exhaustion pauses rather than voids
it, and record throttling events, since API reliability and rate limits are themselves scored
criteria in `docs/DATA_PROVIDER_EVALUATION.md`.

`CheckResult` should carry human-readable evidence — expected value, observed value, and a short
explanation — because QNT-036's report shows failed-check examples, and a bare boolean is useless
to a reader deciding whether the provider or the expectation was wrong. A `not applicable` outcome
is essential and distinct from a pass: a split check on a security that never split must not
inflate a score.

Timestamps in run metadata are timezone-aware UTC (DEC-005). Results land in `data/derived/`
(`docs/ARCHITECTURE.md`) as Parquet or an equally inspectable structured format, tagged with the
input versions per QUANT_PRINCIPLES §4.

## Dependencies
QNT-026 — the provider interface, raw store and fake provider the runner drives. QNT-027 — the
validation universe and expected facts that define the matrix and the checks' expectations.

## Risks
A harness that only ever runs against the fake provider can encode assumptions no real API meets —
pagination shapes, partial failures, inconsistent identifiers. Mitigated by building the fake from
the response shapes documented in QNT-028's research and by treating the first real adapter run as
a harness-validation exercise, expecting to revise the runner. A second risk is burning paid API
quota on repeated runs; mitigated by replay mode and subset selection.

## Testing requirements
`tests/bakeoff/test_harness.py` (matrix enumeration, subset selection, run metadata, resumability),
`tests/bakeoff/test_checks.py` (registry, applicability, the four outcome kinds, exception capture)
and `tests/bakeoff/test_results.py` (persistence schema, run isolation, replay from stored
payloads). All against the fake provider with network access disabled. No `timetravel` marker
applies to the runner itself, since it evaluates providers rather than serving historical queries;
checks that assert point-in-time properties carry their own markers in QNT-035.

## Documentation requirements
`docs/DATA_PROVIDER_EVALUATION.md` method section updated to describe how a run is executed,
where results and raw payloads land, and how to reproduce a published result. A README in
`src/trp/bakeoff/` explaining how to write and register a new check.

## Completion notes
2026-08-16. `src/trp/bakeoff/{checks,results,harness,__main__}.py` + README. Runner
enumerates the (provider x entry x dataset) matrix with subset selection by provider,
market, awkward property and dataset; run metadata records universe and adapter versions.
Raw persists through the QNT-026 store BEFORE checks; the harness stamps its canonical
request params onto stored payloads so replay finds them by identity — replay from the
raw store is automatic whenever matching payloads exist (tested: second run succeeds with
a provider scripted to explode). Check protocol: ABC with name/criterion/datasets/
properties + `run(entry, payloads) -> [Finding]`; registry; findings carry
expected/observed/explanation; exceptions become `error` results with tracebacks (tested).
Fetch outcomes are five-way distinguishable (ok/empty/unsupported/rate_limited/
provider_error, tested). Rate-limit backoff honours retry-after with injectable sleep and
a retry budget; throttle events recorded per cell. Results: `metadata.json` +
append-only `cells.jsonl` per run id — inspectable, diffable, resumable (completed cells
skipped; completed runs never overwritten). CLI `python -m trp.bakeoff` with subset flags;
its adapter table is empty until QNT-031…033 unblock, and says so. One reference check
(`payload_presence`) ships; QNT-034/035 add the real ones. Deviations: results are JSONL
rather than Parquet (equally structured/inspectable, better fit for append+resume; the
report generator can frame them); per-provider paced sleep beyond backoff is deferred to
the first real-adapter run. Tests: `tests/bakeoff/test_harness.py` (9, incl. end-to-end
against the fake with no network). Green.
