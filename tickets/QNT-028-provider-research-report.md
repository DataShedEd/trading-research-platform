# QNT-028 — Provider research and shortlist report

- **Ticket ID:** QNT-028
- **Status:** BACKLOG
- **Priority:** P1
- **Epic:** EPIC 5 — Data Provider Bake-Off

## Problem
Three adapter tickets (QNT-031…033) each require a paid subscription, and every one of them is
blocked until somebody decides which providers are worth paying for. That decision is currently
resting on three names picked before any research was done, with no current pricing, no knowledge
of which tiers actually include delisted securities or point-in-time fundamentals, and no check on
whether the licence even permits storing raw payloads — which the platform's whole architecture
depends on. Marketing pages are unreliable on exactly the points that matter, and the criteria the
platform cares about (delisted coverage, PIT availability) are the ones vendors describe most
loosely.

## Objective
Produce a desk-research report covering the incumbent candidates and any others worth considering,
with pricing, tiers, rate limits, licensing and PIT/delisted claims verified at the time of
writing, ending in a shortlist recommendation written into `docs/DATA_PROVIDER_EVALUATION.md` for
the owner's subscription decision.

## Scope
Research and a written report on: **EODHD**, **Financial Modeling Prep (FMP)**, **Tiingo**, plus
discovered candidates — at minimum considering Sharadar via Nasdaq Data Link, SimFin, Finnhub,
Norgate Data, and entry tiers of LSEG/Refinitiv — with any others found during the search. Output
is edits to `docs/DATA_PROVIDER_EVALUATION.md` (provider notes and pricing section, plus a
recommendation section) and, where a claim is load-bearing, a dated source reference.

## Out of scope
Writing any code; contacting providers' sales teams; purchasing anything — the purchase is an owner
decision this report informs. Empirical testing of the claims (that is the entire point of
QNT-029…036, which will contradict some of them).

## Acceptance criteria
- [ ] Each candidate has a section recording, with the date the information was verified and a
      source reference: available datasets by market, historical depth claimed, the specific tier
      required for the platform's needs, that tier's price, documented rate limits and bulk
      download paths, and API/authentication model.
- [ ] Licensing is addressed explicitly for each candidate, stating whether storing raw payloads
      indefinitely, deriving canonical data from them, and retaining data after cancellation are
      permitted — with the relevant clause referenced, and a clear "unclear, needs asking" where
      the terms do not say.
- [ ] The two highest-weighted criteria are answered per candidate as specifically as the public
      information allows: whether delisted securities are covered (and back to when), and whether
      fundamentals carry announcement/filing timestamps, first-known availability, and distinct
      restatement records.
- [ ] At least three candidates beyond the original three are assessed and either shortlisted or
      excluded with a stated reason, so the shortlist is a comparison rather than a default.
- [ ] `docs/DATA_PROVIDER_EVALUATION.md` contains a recommendation section naming which providers
      to subscribe to for the bake-off, in what order, at what monthly cost, with the reasoning and
      the main uncertainty in each recommendation stated.
- [ ] The report states prominently that this is an **OWNER DECISION GATE**: subscription purchase
      requires owner sign-off, and QNT-031…033 remain blocked on API keys until that sign-off
      happens.

## Technical notes
`docs/DATA_PROVIDER_EVALUATION.md` sets the standard: "We do not trust marketing pages." That
applies to this ticket too — the report's job is not to conclude which provider is best, but to
narrow the field to those worth paying to test, and to flag the claims most likely to be false so
the harness checks them first. Where a vendor's documentation and its marketing disagree, record
both and note the discrepancy.

Pricing and tiers change frequently, so date every figure and note the currency and billing period
(monthly versus annual commitment). A provider whose delisted coverage sits behind a tier costing
several times the headline price should be recorded at the price of the tier actually needed, since
that is what the cost criterion in the scoring table means.

Licensing is the criterion most likely to be quietly disqualifying. The architecture stores raw
payloads permanently as the audit trail and reprocessing source; a licence forbidding retention
would require a documented exception (`docs/ARCHITECTURE.md` allows non-retention only where
licensing forbids storage) and materially weakens the platform's reproducibility guarantee
(QUANT_PRINCIPLES §4). Treat an unclear licence as a risk to record, not a problem to assume away.

For each candidate, note whether a free tier or trial exists that would allow the harness to be
exercised before any purchase — that materially changes the order in which adapters can be built,
and might let one adapter land before the decision gate rather than after.

The point-in-time question is the one vendors answer most loosely: "historical fundamentals" almost
always means the current view of history. Look specifically for an as-reported or point-in-time
product, filing timestamps in the API response schema, and any statement about restatement
handling; record what the response schema actually contains where sample responses are published,
in preference to prose claims.

## Dependencies
QNT-003 — settings define where provider credentials will live once a subscription exists, which
the report's onboarding notes should reference.

## Risks
Published pricing and terms go stale quickly, so a report written now may misinform a decision made
later; mitigated by dating every claim and stating a re-verification expectation before purchase. A
second risk is anchoring: writing the report as a justification for the three names already in the
docs. Mitigated by requiring at least three additional candidates to be assessed and excluded on
stated grounds. Finally, the empirical results from QNT-034…036 may contradict this report
outright — which is the intended outcome of the method, not a failure of it.

## Testing requirements
No code, so no unit tests. Verification is documentary: every quantitative claim in the report
carries a source and a verification date, and a reviewer must be able to re-check any pricing or
licensing statement from the reference given. If any helper script is written to collect published
pricing pages, it lives under `scripts/` and is excluded from `make check` coverage expectations.
No `timetravel` marker applies — this ticket touches no historical data.

## Documentation requirements
`docs/DATA_PROVIDER_EVALUATION.md`: provider notes and pricing section filled in, recommendation
section added, and the owner-decision-gate notice made prominent near the top. A `DECISIONS.md`
entry once the owner has chosen, recording which providers were subscribed to and why — the
decision itself is the owner's, but the log entry is part of this work.

## Completion notes
_Not started._
