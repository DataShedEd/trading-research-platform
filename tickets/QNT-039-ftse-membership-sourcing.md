# QNT-039 — FTSE index membership sourcing

- **Ticket ID:** QNT-039
- **Status:** BACKLOG
- **Priority:** P1
- **Epic:** EPIC 6 — Historical Universe Engine

## Problem
The membership schema and query API are empty vessels until real constituent history is loaded into
them. Historical FTSE 100/250/350 membership is the hardest data in the platform to obtain
honestly: providers overwhelmingly publish *current* constituents, historical constituent files are
frequently reconstructed from surviving names, and index reviews are quarterly events whose
effective dates are easy to record a few days wrong. Loading such data without recording its
provenance and limitations would produce a universe that looks authoritative and is quietly
survivorship-biased.

## Objective
Source historical FTSE 100, FTSE 250 and FTSE 350 constituent changes from provider data and/or a
curated quarterly-review history, ingest them into the QNT-037 membership schema, and document the
coverage and quality caveats honestly enough that a later research result can be discounted
appropriately.

## Scope
`src/trp/universe/sources/ftse.py` — a loader turning raw constituent-change data into
`UniverseMembership` records; support for two input shapes: provider constituent snapshots or
change lists, and a curated quarterly-review file checked into the repository under
`data_sources/ftse/` (small, versioned, human-readable CSV or YAML with a documented column
contract).

Also in scope: resolution of index constituent names/tickers to `security_id` through the security
master, including a reject list for names that cannot be resolved; derivation of FTSE 350 as the
union of 100 and 250 where the sources supply the two separately; a generated coverage report
recording, per universe, the first and last covered date, the number of change events, the
resolution failure rate, and the known caveats.

## Out of scope
The membership schema itself (QNT-037); the query API (QNT-038); the broad rules-based UK universe
(QNT-040); the survivorship acceptance suite (QNT-041); FTSE index *level* or benchmark return
series, which belong to QNT-055.

## Acceptance criteria
- [ ] A documented loader ingests FTSE 100 and FTSE 250 constituent history into
      `universe_membership` with `source` identifying the specific origin (provider name and
      endpoint, or the curated file and its revision), and FTSE 350 is derived from the two.
- [ ] Every ingested row passes the QNT-037 invariants; the loader is re-runnable and produces
      identical output from identical inputs.
- [ ] Constituent names or tickers that cannot be resolved to a `security_id` are written to an
      explicit rejects file with the reason, and the run reports the resolution failure rate; a
      failure rate above a configured threshold fails the load rather than silently loading a
      partial universe.
- [ ] Membership spells reflect index review effective dates, and at least one known historical
      promotion and one known demotion are asserted against hand-checked fixture dates.
- [ ] A coverage report is generated documenting, per universe, the covered date range, event
      counts, resolution failures, and each known quality caveat — including whether the source is
      a reconstructed history and whether intra-quarter changes (fast-entry, deletion on
      acquisition) are captured.
- [ ] Securities that later delisted or were acquired are present in the loaded history, verified
      by a test naming specific companies rather than by aggregate counts.

## Technical notes
Prefer change events over snapshots where both are available: a list of "added on date / removed on
date" reconstructs spells directly, whereas periodic snapshots leave the exact effective date
uncertain and can miss a security that joined and left between two snapshots. Where only snapshots
exist, record the resulting date uncertainty as a caveat rather than pretending to daily precision.

Identifier resolution is the hard part. Index history typically identifies constituents by company
name or by the ticker current at the time, both of which must go through the effective-dated
identifier map (QNT-007/QNT-009) using the *event date*, never today. Resolving a 2009 ticker with
today's mapping is exactly the misattribution that map exists to prevent, and an assertion should
pin that the resolution call passes the event date.

Where a provider supplies only current constituents, say so and do not use it for history. A
curated quarterly-review file assembled from FTSE Russell review announcements is preferable to a
reconstructed provider file, and the two can coexist as separate `source` values so their
disagreements are measurable rather than merged.

Conservative treatment of ambiguity: if it is unclear whether a security was a member on a given
date, the honest options are to exclude it and document the exclusion, or to record the uncertainty
window. Silently including it flatters any strategy that would have held it.

The coverage report is a deliverable, not a log line — it is the document a future reader consults
before trusting a backtest that used these universes, and per QUANT_PRINCIPLES §5 it must state
what could flatter results.

## Dependencies
QNT-037 — supplies the membership schema and invariants the loader writes through.
QNT-028 — supplies the ingested provider data and adapter surface the provider-sourced constituent
history is read from.

## Risks
The dominant risk is that the only obtainable historical constituent data is itself reconstructed
from surviving companies, which would embed survivorship bias beneath an apparently
point-in-time API. This cannot be fully eliminated; it is mitigated by recording provenance per
row, by cross-checking sources where two exist, and by stating the limitation prominently in the
coverage report and in `RESEARCH_METHODOLOGY.md` so results are discounted rather than trusted.

Secondary risk: index review effective dates recorded a few days early would let a backtest trade a
promotion before it was announced. Mitigated by preferring the effective date over the announcement
date for membership and by asserting known review dates in tests.

Licensing may restrict storage or redistribution of provider constituent data; the curated file
path exists partly so the repository is not dependent on redistributable provider history.

## Testing requirements
`tests/universe/test_ftse_sourcing.py` — loader output against a fixture change list, rejects
handling, FTSE 350 derivation as the union of its components, and hand-checked promotion and
demotion dates.

`tests/timetravel/test_ftse_membership.py` (marker `timetravel`) — a FTSE 100 query for a date in
2012 must include companies that subsequently failed or were acquired, and must exclude companies
that joined the index after that date; identifier resolution within the loader must be shown to use
the event date by asserting that a security whose ticker was reassigned resolves to the company
that held the ticker then, not the one holding it now.

## Documentation requirements
`docs/DATA_MODEL.md` universes section documenting the FTSE universe names and their sources. A new
`docs/UNIVERSE_COVERAGE.md` (or the generated coverage report committed to `docs/`) recording
coverage ranges and caveats. `docs/RESEARCH_METHODOLOGY.md` note that results on FTSE universes must
cite the coverage caveats. A `DECISIONS.md` entry recording the chosen source of record.

## Completion notes
_Not started._
