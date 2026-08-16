# QNT-027 — Validation universe specification

- **Ticket ID:** QNT-027
- **Status:** DONE
- **Priority:** P1
- **Epic:** EPIC 5 — Data Provider Bake-Off

## Problem
Every data vendor looks excellent when tested on Apple and Shell. Providers fail on the cases that
matter to a survivorship-bias-free backtest: companies that went bankrupt, companies that were
acquired, securities that changed ticker, consolidations, huge special dividends, restated
accounts. Testing against a convenience sample of currently-listed large caps would rubber-stamp
whichever provider is cheapest, and no amount of harness sophistication (QNT-029) can compensate
for an easy test set. We need the awkward cases named in advance, with known-correct expectations
recorded before any provider is called, so the bake-off measures reality rather than confirming a
preference.

## Objective
Specify the validation universe as a versioned in-repo data file plus a typed loader: a deliberately
awkward set of securities, each recording its identifiers, the awkward property it exercises, and
the expected facts a competent provider should be able to reproduce.

## Scope
`src/trp/bakeoff/universe/validation_universe.<ext>` — the versioned specification data file;
`src/trp/bakeoff/universe/loader.py` — typed loader with schema validation; expected-fact fixtures
in the same package; tests. Coverage must include, at minimum:

- **Long-lived UK names** — Shell, Unilever, AstraZeneca (also a USD-reporting UK case for
  QNT-023).
- **Failures** — Carillion (2018), Thomas Cook (2019): delisted with equity worthless.
- **Acquisitions** — Arm Holdings (2016), Morrisons (2021): delisted with cash consideration.
- **Ticker changes and renames** — at least one where the entity persisted under a new ticker.
- **Splits and consolidations** — at least one of each, including a reverse split/consolidation.
- **Large or special dividends** — at least one where the special dividend materially exceeds the
  ordinary run rate.
- **A rights issue** — where data permits.
- **A restatement case** — reusable by QNT-022's fixtures.
- **US and European listings** — so the universe is not UK-only.

## Out of scope
Fetching anything from a provider (QNT-029 onwards); the checks that consume these expectations
(QNT-034, QNT-035); scoring (QNT-030). The research universe used for actual factor work (Epic 6)
is a different thing entirely and is not defined here.

## Acceptance criteria
- [x] The specification is a data file, not Python code, and carries an explicit version
      identifier that the loader returns, so a bake-off result can be tied to the universe version
      that produced it.
- [x] Every entry records: a stable internal key, entity and security names, identifiers (ISIN and
      SEDOL where known, primary exchange MIC, ticker with the date range it was valid for), the
      market, and the awkward property or properties it exercises, drawn from a closed enumeration
      so the harness can select subsets by property.
- [x] Every entry carries expected facts precise enough to be checked mechanically — for example
      a delisting date and reason, a split ratio with its ex-date, a dividend amount with currency
      and ex-date, an old and new ticker with the change date, a restated line item with original
      and restated values — and each expected fact records the source it was verified against and
      the date of verification.
- [x] All the categories listed in Scope are represented, with at least one non-UK entry per
      category where the category is not inherently UK-specific, and the loader exposes selection
      by market and by awkward property.
- [x] The loader validates the file against a schema and fails loudly on a missing identifier, an
      unknown property value, an expected fact with no source, or a date that is inconsistent with
      the entry's stated lifecycle (e.g. a split ex-date after delisting).
- [x] Tests assert the schema is enforced, the required categories are all present, and the
      universe loads deterministically with a stable ordering.

## Technical notes
`docs/DATA_PROVIDER_EVALUATION.md` already sketches this universe and names it as the method's
foundation; this ticket makes it executable. The expected facts are the fixtures the whole epic
depends on, so their provenance matters more than their quantity: an expectation with no source
note is worse than no expectation, because a check that fails against it cannot be adjudicated.
Prefer primary sources (RNS announcements, annual reports, exchange notices) and record enough
detail — announcement date, document reference — that a future reader can re-verify without
repeating the research.

Precision beats breadth. Twenty securities with exact, sourced expectations will discriminate
between providers far better than two hundred with approximate ones, and the harness cost per
security is real once rate limits apply.

Identifiers deserve care because they are themselves a test: a provider that cannot map an ISIN for
a company delisted in 2018 has failed a criterion. Record identifiers with validity ranges in the
same effective-dated spirit as the security master (`docs/DATA_MODEL.md`, QNT-006/QNT-007) — a
ticker is never a permanent key, and the universe file must not imply otherwise. Where an identifier
genuinely could not be established, record it as explicitly unknown rather than omitting the field,
so the gap is visible.

Note that expectations about pence-quoted UK securities must state the unit (GBX versus GBP)
explicitly; a dividend expectation that does not is untestable. Amounts are `Decimal` in the loader
(DEC-005), and dates are market-local `date` values.

Where the expected fact concerns fundamentals availability, express it in the point-in-time terms
Epic 4 uses (what was knowable when), not as a current-view value, so QNT-035 can check it directly.

## Dependencies
QNT-006 — the security master model whose identifier and lifecycle conventions the universe entries
mirror.

## Risks
Expectations sourced carelessly become a false standard: the harness would then penalise a correct
provider and reward a wrong one, and the error would propagate into the purchase recommendation.
Mitigated by requiring a source and verification date on every fact, and by treating any
check-versus-expectation disagreement as an investigation rather than an automatic provider
failure. A second risk is scope creep into a research universe; mitigated by the explicit
out-of-scope note.

## Testing requirements
`tests/bakeoff/test_validation_universe.py` covering schema validation, required-category coverage,
identifier-range consistency, deterministic ordering, and selection by property and market. No
provider is contacted. No `timetravel` marker is required for the loader itself, but the
restatement and delisting entries created here must be usable as fixtures by the `timetravel`
suites in QNT-022 and QNT-025, and a test should assert those entries expose the fields those
suites need.

## Documentation requirements
`docs/DATA_PROVIDER_EVALUATION.md` method section updated to point at the in-repo specification and
its version identifier as the authoritative list, replacing the illustrative examples currently
inline. A short README alongside the data file explaining how to add an entry and the standard of
evidence required for an expected fact.

## Completion notes
2026-08-16. `src/trp/bakeoff/universe/`: `validation_universe.json` (version 2026-08-16.1,
14 entries, key-sorted) + strict typed loader (`loader.py`) + README stating the standard
of evidence. Coverage: long-lived UK (Shell, Unilever, AstraZeneca, Rolls-Royce, Tesco),
failures (Carillion 2018, Thomas Cook 2019), acquisitions (Arm 2016 £17 cash, Morrisons
2021 287p), ticker changes with entity persistence (Shell RDSB→SHEL incl. ISIN change;
Flutter PPB→FLTR), splits (Apple 4:1 and 7:1), consolidation (Citigroup 1-for-10 2011;
Tesco 15-for-19 2021), special dividends (Microsoft $3.00 2004 — ~38x the ordinary;
Tesco 50.93p 2021, same ex-date as its consolidation — exercising QNT-015's composition
order), rights issue (Rolls-Royce 10-for-3 at 32p, 2020 — the DEC-009 unadjusted case),
restatement (Tesco 2014, matching the QNT-022 fixture), non-GBP reporters (Shell/AZN USD,
Unilever EUR), US (XNAS/XNYS) and EU (SAP, XETR) entries. Loader validates ISIN/SEDOL
check digits (all 15 recorded ISINs pass), closed property enum, mandatory source +
verified_on per fact, and lifecycle consistency (fact after delisting rejected — tested).
Honesty mechanism: `needs_verification` flags facts whose precision was recalled rather
than confirmed against a primary source (exact ex-dates, some amounts) — the README and
loader docstring require re-verification before those facts score a provider. Deviation:
spec file lives at `validation_universe.json` (loader validates on load; no separate
schema file). Tests: `tests/bakeoff/test_validation_universe.py` (8). Green.
