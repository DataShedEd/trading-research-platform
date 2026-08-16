# QNT-028 — Provider research and shortlist report

- **Ticket ID:** QNT-028
- **Status:** DONE
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
      *Not ticked:* complete for EODHD, FMP and Tiingo. For candidates excluded on coverage or cost
      (Sharadar, Norgate, LSEG, EDI, Twelve Data) rate limits, bulk paths and auth model are not
      recorded, because those fields cannot change an exclusion made on "no UK data at all" or "no
      obtainable price". Several of those prices are also unobtainable without a login or a sales
      conversation, which is recorded rather than guessed.
- [ ] Licensing is addressed explicitly for each candidate, stating whether storing raw payloads
      indefinitely, deriving canonical data from them, and retaining data after cancellation are
      permitted — with the relevant clause referenced, and a clear "unclear, needs asking" where
      the terms do not say.
      *Not ticked:* done properly for EODHD (Data Storage and Deletion; Personal and Commercial
      Use), FMP (§2.2.1, §2.8, §5, §6.3) and Tiingo (Internal Use Only). Not done for SimFin,
      Finnhub, Marketstack, Alpha Vantage, Polygon/Massive, Twelve Data, Norgate or Sharadar, each
      of which was excluded before licensing became decision-relevant.
- [x] The two highest-weighted criteria are answered per candidate as specifically as the public
      information allows: whether delisted securities are covered (and back to when), and whether
      fundamentals carry announcement/filing timestamps, first-known availability, and distinct
      restatement records.
- [x] At least three candidates beyond the original three are assessed and either shortlisted or
      excluded with a stated reason, so the shortlist is a comparison rather than a default.
- [x] `docs/DATA_PROVIDER_EVALUATION.md` contains a recommendation section naming which providers
      to subscribe to for the bake-off, in what order, at what monthly cost, with the reasoning and
      the main uncertainty in each recommendation stated.
- [x] The report states prominently that this is an **OWNER DECISION GATE**: subscription purchase
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

**2026-08-16 — desk research complete; report written into `docs/DATA_PROVIDER_EVALUATION.md`.**

Thirteen candidates assessed: EODHD, FMP and Tiingo as briefed, plus Sharadar (Nasdaq Data Link),
SimFin, Finnhub, Norgate Data, Polygon.io/Massive, Alpha Vantage, Marketstack, Twelve Data,
LSEG/Refinitiv and Exchange Data International. All prices verified 2026-08-16 against vendor
pages; sterling equivalents use ECB rates for 2026-08-14 (GBP/EUR 1.1703, GBP/USD 1.3537).

**Where the recommendation landed.** Phase 1: EODHD ALL-IN-ONE at €99.99/month month-to-month
(~£85), the only candidate covering UK prices, corporate actions, delisted securities and
fundamentals in one subscription. Phase 2, only if Phase 1 leaves the UK delisted or PIT questions
unanswered: FMP Premium ($59/month billed annually, ~£44) alongside a downgraded EODHD All-World
EOD (€19.99, ~£17), about £61/month. Tiingo is recommended at its free tier only and explicitly
not as a purchase. Peak monthly spend ~£85, inside the ~£100 budget; the two paid providers run
consecutively rather than concurrently, since neither licence allows keeping data after
cancellation.

**Two findings that matter more than the prices.**

1. Both leading candidates forbid retaining data after cancellation — EODHD requires deletion of
   all copies within one month, FMP requires immediate deletion "including data cached" plus a
   signed deletion certificate (§6.3), with an audit right. The permanent raw-payload archive the
   architecture assumes is therefore licensed rather than owned, and QNT-036's durable evidence
   should be derived check results rather than raw payloads for any provider not retained. This
   needs an owner decision and an architecture exception.
2. No candidate in this price bracket sells genuine point-in-time UK fundamentals. FMP carries an
   SEC `acceptedDate` to the second for US filers and EODHD carries `filing_date` plus
   `beforeAfterMarket` on earnings, but neither documents a first-known field or distinct
   restatement records, and whether either populates timestamps for LSE issuers is unknown. UK
   `available_at` will most likely have to be imputed conservatively or sourced from RNS.

**Other things worth knowing.** EODHD ticks delisted data on every plan including Free, but its
delisted documentation is entirely US-worked and its symbol-change-history endpoint is US-only;
its non-US fundamentals start in 2000, so pre-2000 UK fundamentals are unavailable at any personal
tier. FMP gates UK coverage behind Premium and EU coverage plus bulk delivery behind Ultimate
($149/month), which puts UK+US+EU with bulk out of budget. Tiingo's "109,666 global securities"
resolves to US and Chinese stocks plus funds, with no LSE coverage. Sharadar and Norgate are the
best-designed survivorship-bias-free datasets found and are both excluded purely for having no UK
data. Exchange Data International is the only vendor found whose model reportedly sells rather than
rents data — the one licence compatible with a permanent archive — but publishes no prices;
requesting an indicative quote is a suggested owner action.

**Deliberately not verified.** FMP's month-to-month prices (only annual billing is server-rendered),
EODHD's Extended Fundamentals price (by request only) and whether two EODHD personal plans can be
held concurrently, Finnhub's and Twelve Data's current tiers (client-rendered pages), and Sharadar's
price (login required). Each is marked unverified in the report rather than estimated.

**Outstanding.** The `DECISIONS.md` entry required by this ticket's documentation requirements
cannot be written yet: it records which providers the owner chose and why, and that choice has not
been made. It should be written at sign-off, together with the retention-exception decision noted
above.
