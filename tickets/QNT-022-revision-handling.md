# QNT-022 — Revision and restatement handling

- **Ticket ID:** QNT-022
- **Status:** DONE
- **Priority:** P1
- **Epic:** EPIC 4 — Fundamental Data

## Problem
Companies restate. A figure reported in the 2017 annual report can be materially different from
the same period's figure as shown in the 2019 accounts, and providers almost universally serve the
latest view. If ingestion updates a row in place when a restated value arrives, the original figure
is destroyed and a backtest run over 2018 sees numbers nobody could have seen at the time —
frequently *better* numbers, because restatements often follow the discovery of a problem. This is
look-ahead bias of the most flattering and least visible kind.

## Objective
Make revisions and restatements append-only across the fundamentals layer: a new observation of an
already-known (security, statement, line item, period, period type) fact is written as an
additional row with its own `available_at` and revision sequence, never as an update, and an as-of
query between the original filing and the restatement returns the original figures. Delivered as
ingestion-side revision detection and sequencing plus the invariants that guarantee it; the query
API consuming them is QNT-025.

## Scope
`src/trp/canonical/fundamentals/revisions.py`: the revision key definition, a
`classify_observation` function deciding whether an incoming record is a new fact, an unchanged
re-observation, or a revision (and assigning `revision_sequence` / `revised_at` accordingly), and
an assertion helper that a set of records for one key forms a valid revision series. A checked-in
restatement fixture with genuine before/after values. Unit tests and time-travel tests.

## Out of scope
The record type (QNT-020); the taxonomy (QNT-021); the physical Parquet layout and writer
(QNT-024); the public query API (QNT-025); measuring which providers expose revisions at all
(QNT-035).

## Acceptance criteria
- [x] The revision key is defined in one place and documented: (security identifier, statement,
      canonical line item, `period_end`, `period_type`) — currency is not part of the key, and a
      currency change for the same key is treated as a data error rather than a revision.
- [x] `classify_observation` distinguishes new fact, byte-identical re-observation (idempotent
      no-op, no new row), and revision (new row, `revision_sequence` incremented, `revised_at`
      set); re-running ingestion over the same payload twice adds no rows.
- [x] Revisions are only ever appended: there is no code path in the fundamentals layer that
      rewrites or deletes an existing row's `value`, `available_at`, or `revision_sequence`, and a
      test asserts this by re-reading the original row after a restatement has been applied.
- [x] A restatement's `available_at` is the first-known timestamp of the *restatement*, not of the
      original filing, and must be strictly greater than the previous revision's `available_at`;
      violations raise rather than being silently reordered.
- [x] A `timetravel`-marked test using the restatement fixture proves that querying as of a date
      between the original filing and the restatement returns the original value, as of a date
      after the restatement returns the restated value, and as of a date before the original
      filing returns nothing.
- [x] The restatement fixture is documented: real company, period, line item, original value,
      restated value, and both availability dates, with a source note so the expectations can be
      re-verified.

## Technical notes
Append-only is the same discipline the raw layer already uses (`docs/ARCHITECTURE.md`) applied to
canonical fundamentals, and it is what `docs/DATA_MODEL.md` requires: "Revisions are new rows,
never updates". Storage-level enforcement is straightforward once QNT-024's writer never rewrites
partitions in place; this ticket owns the logical rules and the tests that prove them.

Per DEC-005 all timestamps are timezone-aware UTC. Where a restatement has no announcement
timestamp of its own, DEC-007 imputation applies again — conservatively late, using the filing date
of the *document containing the restatement*, and flagged as imputed. Never inherit the original
filing's `available_at` for a restated value: that would make the restatement retroactively visible
and is precisely the leak this ticket exists to prevent.

Distinguishing "unchanged re-observation" from "revision" needs a value comparison that is exact on
`Decimal` and does not treat `100` and `100.00` as different facts; normalise the exponent for
comparison while preserving the original scale on the stored row. Document the choice.

A subtle case worth encoding in tests: a provider that only ever serves the latest view will, on
first ingestion, present a restated figure with no evidence that an original existed. We cannot
invent the original — but we must not present the restated figure as though it had been available
at the original filing date either. The conservative treatment is to use the restatement's own
availability where known, or DEC-007 imputation from the restating document, and to record the
source's revision-visibility capability so QNT-035's checks and the bake-off report can score it.

Restatements also arrive as whole-statement re-filings rather than per-line events, so
classification operates per key across a batch, not per file.

## Dependencies
QNT-020 — the record type, revision-sequence fields, and series-validation helper this ticket
builds on.

## Risks
A provider whose payload silently changes historical values without any revision marker will look
like a stream of unexplained revisions or, worse, like nothing at all if comparison is loose.
Mitigated by exact `Decimal` comparison and by keeping raw payloads immutable so any canonical
disagreement can be traced back. The second risk is a restatement being assigned an availability
earlier than the truth, reintroducing leakage; mitigated by the strict-increase invariant and the
`timetravel` tests.

## Testing requirements
`tests/canonical/test_revisions.py` for classification, idempotence and invariant violations, plus
`tests/timetravel/test_fundamental_revisions.py` (pytest marker `timetravel`) covering the
before/between/after query windows described in the acceptance criteria. The restatement fixture
lives in `tests/fixtures/` and is shared with QNT-025. Include a test asserting that a second
ingestion pass over an identical payload produces an identical row count and identical row
contents.

## Documentation requirements
`docs/DATA_MODEL.md` fundamentals section states the revision key and the append-only rule
explicitly. `RESEARCH_METHODOLOGY.md` gains a note that research results are sensitive to whether
the provider exposes revisions at all, since with a latest-view-only provider the platform's
correctness guarantee is limited to what the provider preserves.

## Completion notes
2026-08-16. `src/trp/canonical/fundamentals/revisions.py`: revision key defined in one
place (currency excluded — `CurrencyChangeError` on change); `classify_observations`
handles batches across keys, distinguishing new fact (sequence 0), unchanged
re-observation (exact Decimal comparison, exponent-normalised, stored scale preserved —
documented) and revision (next sequence, `revised_at` = the restatement's own
`available_at`, never inherited; strict-increase enforced via `RevisionOrderError`).
Re-ingestion idempotence tested at both this layer and storage (QNT-024). Restatement
fixture: Tesco plc 2014 H1 trading-profit guidance (GBP 1,100m announced 29 Aug 2014;
c. GBP 850m after the 22 Sep 2014 overstatement announcement), fully documented with
source notes in `tests/fixtures/fundamentals.py::tesco_restatement`. Latest-view-only
provider limitation documented in RESEARCH_METHODOLOGY (new PIT-querying section).
Timetravel windows (before/between/after) in
`tests/timetravel/test_fundamental_revisions.py`. Tests: `tests/canonical/test_revisions.py`.
All checks green.
