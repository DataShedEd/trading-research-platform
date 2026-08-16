# Data provider evaluation

> **OWNER DECISION GATE.** No subscription is purchased without the owner's explicit sign-off.
> The research below (QNT-028) is an input to that decision, not the decision. QNT-031…033 remain
> blocked on API keys until sign-off happens. See [Recommendation](#recommendation).

Status: **framework defined; empirical evaluation not yet run.** Candidates: EODHD, Financial
Modeling Prep (FMP), Tiingo, plus any discovered during research (QNT-028). This document is
partly generated: the scoring tables below will be produced by the bake-off harness
(`trp.bakeoff`, QNT-036) from real API responses — never from advertised feature lists.

## Method

We do not trust marketing pages. Each candidate is exercised against a deliberately awkward
**validation universe** — now implemented (QNT-027) as the authoritative, versioned
specification at `src/trp/bakeoff/universe/validation_universe.json` (current version
`2026-08-16.1`; typed loader with strict schema validation; see the README alongside it for
the standard of evidence). The illustrative list below describes the categories it covers:

- long-lived current securities (e.g. Shell, Unilever, AstraZeneca);
- delisted securities and outright failures (e.g. Carillion 2018, Thomas Cook 2019);
- acquisitions (e.g. Arm 2016, Morrisons 2021);
- ticker changes and renames;
- notable splits and consolidations;
- large/special dividends (and rights issues where data permits);
- restated financial statements;
- UK, US, and European listings.

For each security the harness fetches securities metadata, prices, corporate actions, and
fundamentals, stores raw payloads, and runs empirical checks with known-correct expectations
(e.g. the split ratio and ex-date actually observed; whether a delisted name exists at all).

## Scoring criteria

Implemented (QNT-030, `trp.bakeoff.scoring`). Weights were **fixed before any real provider
results existed** (weights file `src/trp/bakeoff/weights.json`, version `2026-08-16.1`) —
pre-registration, not post-hoc rationalisation. Empirical criteria are scored as
passes/(passes+fails+errors) over the mapped checks with not-applicable excluded from the
denominator; a criterion nobody measured scores *unmeasured* (excluded, renormalised),
distinct from a dataset the provider simply lacks (scored zero, reason recorded). Declared
criteria come from this document's research, not API checks, and are labelled as such in the
breakdown. **Veto thresholds (DEC-012):** below 0.5 on delisted coverage or 0.25 on PIT
fundamentals ⇒ unsuitable regardless of total. Scores are ordinal; the breakdown and
coverage counts are the real output.

| Criterion | Weight | Kind | What is measured |
| --- | --- | --- | --- |
| Delisted coverage | 0.20 (veto < 0.5) | empirical | Validation-universe delistings present with data to delisting date |
| PIT fundamental availability | 0.20 (veto < 0.25) | empirical | Announcement timestamps present; first-known reconstructible |
| Corporate-action accuracy | 0.15 | empirical | Splits/dividends match known-correct fixtures (dates, ratios, amounts) |
| Identifier stability | 0.10 | empirical | ISIN/SEDOL presence; behaviour across ticker changes |
| Historical depth | 0.10 | empirical | Earliest usable price/fundamental data per market |
| Revision history | 0.05 | empirical | Restatements visible as distinct records |
| API reliability | 0.05 | empirical | Error rates, throttling events, consistency across pulls |
| Rate limits & bulk | 0.05 | declared | Documented limits and bulk paths (QNT-028 research) |
| Licensing | 0.05 | declared | Raw-payload retention constraints (QNT-028 research) |
| Cost | 0.05 | declared | Actual tier needed, per month (QNT-028 research) |

Weight rationale: the top two are the platform's non-negotiables (QUANT_PRINCIPLES §1–2) —
a provider failing either cannot support correct research at any price, hence vetoes rather
than weight inflation alone. Corporate-action accuracy is next because a wrong ratio
corrupts every derived return. Operational criteria (reliability, limits) are inconvenience,
not correctness, and are weighted accordingly. The PIT veto is set low (0.25) because the
research above already shows no in-budget provider offers true PIT fundamentals — the
criterion must be scored honestly without disqualifying every candidate.

**Running the bake-off:** `uv run python -m trp.bakeoff --run-id <id> --provider <name>`
(subsets by `--market/--dataset/--property`; `--resume` continues an interrupted run). Raw
payloads persist to `data/raw/` before any check runs; per-cell results append to
`data/derived/bakeoff/<run_id>/cells.jsonl`; completed runs are never overwritten, and
re-runs replay stored payloads without spending API quota. See `src/trp/bakeoff/README.md`
for the check-writing guide.

## Provider notes and pricing

**Prices verified 2026-08-16** (QNT-028 desk research). Every figure below is quoted in the
currency the vendor publishes. Sterling equivalents are indicative only and use the ECB reference
rates for 2026-08-14: GBP/EUR 1.1703, GBP/USD 1.3537
([frankfurter.dev](https://api.frankfurter.dev/v1/latest?base=GBP&symbols=EUR,USD)). Pricing and
terms go stale quickly — **re-verify every figure immediately before purchase**.

Where a page is rendered client-side and could not be read directly, that is stated. Claims taken
from search-result summaries rather than from the vendor's own page are marked **unverified**;
they are recorded so the bake-off can check them, not so they can be relied on. This section
follows the document's method: marketing claims are hypotheses for QNT-034…036 to falsify.

Two findings apply across the field and are more important than any individual price:

1. **Retention after cancellation is the binding constraint, not cost.** Both leading candidates
   require deletion of all data on termination (EODHD: one month; FMP: immediately, with a signed
   deletion certificate). A "subscribe for one month, bulk-download 30 years, cancel" plan is a
   licence breach at both. The permanent raw-payload archive that `docs/ARCHITECTURE.md` and
   QUANT_PRINCIPLES §4 assume is therefore *licensed, not owned*: it survives only while the
   subscription does. This needs an owner decision, recorded in `DECISIONS.md`, before any purchase.
2. **Nobody in this price bracket sells genuine point-in-time UK fundamentals.** Announcement
   timestamps exist for US SEC filers (because EDGAR publishes them free); for LSE issuers the
   vendors surface a filing or report date at best, and no candidate publicly claims distinct
   restatement records or a first-known (`available_at`) field. Expect to impute `available_at`
   conservatively for UK fundamentals per QUANT_PRINCIPLES §1, and treat any vendor claim to the
   contrary as a thing to test rather than believe.

### EODHD (eodhd.com)

Personal-use plans, EUR, month-to-month or annual. The plan feature matrix was read from the
server-rendered pricing page markup, so the tier-by-tier ticks below are the vendor's own, not an
inference ([eodhd.com/pricing](https://eodhd.com/pricing)).

| Tier | Monthly | Annual | Delisted | EOD + splits/divs | Fundamentals | Calls |
| --- | --- | --- | --- | --- | --- | --- |
| Free | €0 | €0 | yes | yes | no | 20/day |
| EOD Historical Data — All World | €19.99 (~£17) | €199.90 | yes | yes | no | 100,000/day, 1,000/min |
| EOD+Intraday — All World Extended | €29.99 (~£26) | €299.90 | yes | yes | no | 100,000/day, 1,000/min |
| Fundamentals Data Feed | €59.99 (~£51) | €599.90 | yes | no | yes | 100,000/day, 1,000/min |
| ALL-IN-ONE | €99.99 (~£85) | €999.90 (€83.33/mo) | yes | yes | yes | 100,000/day, 1,000/min |
| Internal Use (commercial) | €399 | €3,990 | — | — | — | unlimited/day |

**Tier actually needed:** prices, corporate actions *and* fundamentals for the bake-off means
**ALL-IN-ONE at €99.99/month (~£85)**. The pricing matrix implies a cheaper route — All-World EOD
(€19.99) plus Fundamentals Data Feed (€59.99) = €79.98 — but whether two personal plans can be held
concurrently on one account is not stated anywhere public. **Open question: ask support before
assuming the cheaper combination exists.**

**Coverage and depth.** 60+ exchanges (70+ claimed for fundamentals), explicitly including LSE;
EODHD states it licenses UK data from LSE directly. "30+ years" of EOD on all paid tiers.
Fundamentals depth is uneven and the vendor says so: major US companies from 1985, **non-US symbols
from 2000 only**, and minor companies just the last 6 years / 20 quarters
([fundamentals docs](https://eodhd.com/financial-apis/stock-etfs-fundamental-data-feeds)). For a
UK-first platform this is the single most consequential coverage limit on the page: pre-2000 UK
fundamentals are not offered at any personal tier.

**Delisted coverage — highest-weighted criterion.** Delisted data is ticked on *every* tier
including Free. Retrieval is `GET /api/exchange-symbol-list/{EXCHANGE}?delisted=1`, after which the
standard EOD/fundamentals/dividends/splits endpoints accept the delisted ticker. The documented
tiering by delisting date is the thing to check first: delisted **after 2021** gets EOD +
fundamentals + dividends + splits + intraday; **after 2018** the same minus intraday; **before
2018, EOD only** ([delisted docs](https://eodhd.com/financial-apis/delisted-stock-companies-data-2)).
Carillion (Jan 2018) and Thomas Cook (Sep 2019) sit either side of that boundary, so the validation
universe hits it deliberately. The same page's worked examples are all US, and it states that
symbol-change history (`/api/symbol-change-history`) supports **US exchanges only** — a direct hit
on the identifier-stability criterion for UK renames. **The page does not claim LSE delisted
coverage; it does not deny it either. This is the first thing the harness must measure.**

**PIT fundamentals.** Financial statements carry `date` and `filing_date` per annual and quarterly
report, and the Earnings::History block carries `reportDate`, `date`, `beforeAfterMarket` and
`epsActual`/`epsEstimate`. That is a usable — if coarse — announcement signal, and
`beforeAfterMarket` is genuinely useful for intraday-safe `available_at` imputation. There is **no
documented first-known field and no statement about restatements anywhere in the fundamentals
documentation**; the working assumption must be that the API returns the current view of history
and silently overwrites restated figures. Whether `filing_date` is populated for LSE issuers at all
is unknown and is a bake-off question.

**Bulk.** `/api/eod-bulk-last-day/{EXCHANGE}` returns a whole exchange in one call (100 API calls
per exchange, +1 per ticker when selecting symbols) and accepts a `date` parameter for historical
days; the documentation's examples are US exchanges (NYSE/NASDAQ/BATS/AMEX) and do not list LSE
([bulk docs](https://eodhd.com/financial-apis/bulk-api-eod-splits-dividends)). Included on
All-In-One, All-World and All-World Extended. **Bulk fundamentals is not included in any published
plan** — it requires an unpublished "Extended Fundamentals" plan, price by request only
([bulk fundamentals docs](https://eodhd.com/financial-apis/bulk-fundamentals-api-via-extended-fundamentals-plan)).
Without it, a full LSE fundamentals pull is one request per ticker at 10 calls each; against a
100,000/day budget that is workable for a few thousand UK tickers but not casual.

**API/auth.** REST, JSON or CSV, `api_token` query parameter. No OAuth. Credentials would live per
the settings work in QNT-003.

**Licensing.** The terms are explicit and unhelpful for this architecture
([terms and conditions](https://eodhd.com/financial-apis/terms-conditions)):

- *Data storage and deletion*: "EOD Historical Data Information may be stored on the subscriber's
  premises during the active subscription period", and on termination the subscriber must "delete
  all copies of the data in their possession within one (1) month".
- *Personal and commercial use*: a Non-Professional User is "an individual who views or uses […]
  solely in a personal capacity for their own personal investment activities" and may not sell,
  resell, retransmit, redistribute, display or grant access to the Information.

So: storing raw payloads locally is **permitted while subscribed**; deriving canonical data from
them is not addressed either way (**unclear, needs asking** — specifically whether derived
non-reproducible values, e.g. factor exposures, must also be deleted); retention after cancellation
is **prohibited**. A personal research platform with no third-party access sits inside the
Non-Professional definition; publishing charts built from the data would not.

**Free tier / trial.** Yes — 20 calls/day, "past year" data range, and delisted data is ticked. Not
enough for a bake-off run, but enough to build and smoke-test the QNT-031 adapter before any
purchase, which is the useful property.

**Open questions for the bake-off.** (a) Does `exchange-symbol-list/LSE?delisted=1` return anything,
and does it include Carillion and Thomas Cook? (b) Is `filing_date` populated for LSE issuers, or
null outside the US? (c) Are LSE dividends quoted in GBX or GBP, and is the unit signalled in the
payload — EODHD's own blog records LSE dividend coverage as a relatively recent expansion, adding
`payment date` for "more than 500 tickers"
([blog](https://eodhd.com/financial-apis-blog/update-for-dividends-on-london-stock-exchange)),
which suggests the UK dividend history is younger than the 30-year price history. (d) Is ISIN
present for delisted UK names, and is SEDOL present at all? (e) Can All-World EOD and Fundamentals
Data Feed be held concurrently? (f) What does Extended Fundamentals cost?

### Financial Modeling Prep (FMP)

USD, personal-use plans. The pricing page is a Next.js app whose Monthly/Annual toggle is
client-side; only the **annually-billed** prices are present in the served markup, so those are what
is verified below. **Monthly-billed prices could not be verified** (the page advertises "Up To 34%
Discount" for annual, implying month-to-month is materially higher — do not assume the annual
figure) ([pricing-plans](https://site.financialmodelingprep.com/pricing-plans)).

| Tier | Price (billed annually) | Coverage | Rate limit | Bandwidth/30d |
| --- | --- | --- | --- | --- |
| Basic | Free | US, EOD, 5y | 250 calls/day | 500 MB |
| Starter | $22.00/mo (~£16) | **US only**, 5y, annual fundamentals | 300 calls/min | 20 GB |
| Premium | $59.00/mo (~£44) | **+ UK and Canada**, 30+ years, full fundamentals | 750 calls/min | 50 GB |
| Ultimate | $149.00/mo (~£110) | **Global**, full historical, **bulk and batch delivery** | 3,000 calls/min | 150 GB |

**Tier actually needed:** **Premium ($59/mo annually billed, ~£44)** is the minimum that covers the
UK at all — the cost criterion must use this figure, not Starter's. Note what Premium does *not*
include: EU coverage (Ultimate) and bulk/batch delivery (Ultimate). A platform that wants UK + US +
EU with bulk download needs **Ultimate at $149/mo (~£110)**, which alone exceeds the budget. The
honest reading is that FMP is affordable for UK+US and expensive for UK+US+EU.

**Delisted coverage.** A dedicated endpoint exists, `/stable/delisted-companies?page=&limit=`,
paginated, and the plan comparison table lists "Delisted Companies" as a Company Information
feature. The documentation describes the use case (avoiding delisted stocks) but **never states
which exchanges it covers or how far back**
([docs](https://site.financialmodelingprep.com/developer/docs/stable/delisted-companies)). Given the
rest of the API is US-first and the delisted endpoint has no exchange parameter, treat "covers UK
delistings" as unproven. Community reports of non-US suffixes (`.L`, `.DE`) appearing in FMP symbol
lists are **unverified** and about the symbol list, not the delisted list.

**PIT fundamentals.** FMP is the strongest candidate here *for US filers*: the income statement
response carries `filingDate` (e.g. `2024-11-01`) and `acceptedDate` with a to-the-second timestamp
(e.g. `2024-11-01 06:01:36`) — the latter being the SEC acceptance timestamp, which is exactly the
`available_at` semantics QUANT_PRINCIPLES §1 wants. That schema detail comes from FMP's own docs
site but was read via search summary because the schema widget is client-rendered, so treat the
exact field spelling as **to be confirmed against a live response** (FMP's legacy v3 spelled it
`fillingDate`). There is also an "As Reported" statement family (`as-reported-income-statements`
etc.) which is closer to as-filed data than the normalised statements. **No restatement history and
no first-known field are claimed anywhere.** For LSE issuers there is no SEC acceptance timestamp to
inherit, so whether `acceptedDate` is populated, null, or silently copied from `date` is the
question that decides FMP's PIT score.

**Bulk.** Bulk and batch delivery is Ultimate-only. At Premium, ingestion is per-symbol at 750
calls/minute, which is generous enough for a few thousand UK tickers.

**API/auth.** REST, JSON, `apikey` query parameter. `/stable/` endpoints are current; `/v3/` is
legacy.

**Licensing.** Stricter than EODHD, and in one place stricter than the API implies
([terms of service](https://site.financialmodelingprep.com/terms-of-service), last updated
2023-08-01):

- §6.3 *Data Deletion*: "Upon termination of this Agreement, Customer must delete all Data it has
  received from FMP under all applicable Order Forms, **including data cached**, and sign the Data
  Deletion Agreement in Exhibit A", with an audit right if FMP suspects continued use.
- §2.2.1 *Personal Use*: personal, non-business, non-commercial only; may not integrate the Data
  into tools accessible by third parties; and — read literally — "The Customer may not copy or
  download any content from the Services except with the prior written approval of FMP."
- §2.8 *Customer Security*: the customer must notify FMP of "the IP and domain aliases of any
  location where data is stored or processed".
- §5: on termination the customer must destroy confidential information but "if the Agreement is not
  terminated for cause, the Customer may retain copies of the reports or information printed or
  obtained through The Services" — which sits awkwardly beside §6.3's flat deletion requirement.

Storing raw payloads while subscribed is **implicitly permitted** (§2.8 contemplates storage
locations) but §2.2.1's "may not copy or download" clause is **unclear and needs asking**, since
using an API is downloading. Retention after cancellation is **prohibited** and, unlike EODHD,
requires signing a deletion certificate. The §5/§6.3 contradiction is worth a written question
before purchase; a vendor's answer in writing is the only thing that resolves it.

**Free tier / trial.** Yes — Basic, 250 calls/day, US EOD and reference data, no card. Enough to
build the QNT-032 adapter and to characterise response schemas before any purchase.

**Open questions for the bake-off.** (a) What is the month-to-month price of Premium? (b) Does
`delisted-companies` return any LSE names? (c) Are `filingDate`/`acceptedDate` populated for LSE
issuers? (d) Does "UK coverage" at Premium mean prices only, or fundamentals too? (e) Does the
as-reported statement family differ from the normalised one for a known restatement case?

### Tiingo

| Tier | Monthly | Annual | Limits |
| --- | --- | --- | --- |
| Starter | $0 | — | 500 unique symbols/mo, 50 req/hr, 1,000 req/day, 1 GB/mo |
| Power (individual) | $30 (~£22) | $300 | 109,666 symbols/mo, 10,000 req/hr, 100,000 req/day, 40 GB/mo |
| Power (commercial) | $50 | $499 | as above |

Verified at [tiingo.com/about/pricing](https://www.tiingo.com/about/pricing) and
[tiingo.com/pricing](https://www.tiingo.com/pricing).

**Assessment: excluded from the paid shortlist on coverage.** Tiingo's headline is 109,666 global
securities, but the same page breaks that down as 49,241 "US & Chinese stocks" plus 60,425
ETFs/mutual funds, and Tiingo's own comparison writing points readers needing "dozens of
international exchanges" elsewhere. There is no claim of LSE coverage, which is disqualifying for a
UK-first platform whatever the price. Fundamentals are a separately-priced add-on sourced from a
third party, with **no published price** ("contact sales"), and are described as covering tickers
that file with the SEC — i.e. US only. Delisted coverage is claimed for fundamentals ("actively
listed and delisted tickers that file earnings reports with the SEC"), again US-scoped. Licensing is
"Internal Use Only": data "may only be used for your own personal use and you may not display or
share the data with another person or organization" — no statement found on retention after
cancellation, so **unclear, needs asking**; it is also moot while Tiingo is not shortlisted.

**Recommended role: free tier only.** The Starter tier costs nothing and gives an independent US
price series, which is a useful cross-check on US corporate-action accuracy in QNT-034 without
spending anything. Keep the adapter (QNT-033) but do not buy Power.

### Sharadar (via Nasdaq Data Link) — excluded

US equities only, back to 1998 (prices) / 1990 (fundamentals), explicitly survivorship-bias-free
("includes active and delisted tickers") and marketed as "point-in-time ready" with as-reported
dimensions ([sharadar.com](https://sharadar.com/),
[data.nasdaq.com/databases/SFA](https://data.nasdaq.com/databases/SFA)). On the two
highest-weighted criteria this is the best-designed dataset in the field. **Excluded solely because
it has no UK, EU or non-US coverage of any kind**, and UK equities are the platform's first
priority. Price could not be verified: Nasdaq Data Link's pricing page is client-rendered and
QuantRocket's Sharadar pricing page requires a login. Worth revisiting only if the platform's focus
ever moves to US equities — at which point it should be the leading candidate for PIT fundamentals.

### SimFin — excluded

FREE / START $15 / BASIC $35 / PRO $71 per month (annual billing shows a 40% discount), with
history depth tiered 5–7 / 10 / 15 / 20+ years and CSV bulk download from START upward
([simfin.com/en/prices](https://www.simfin.com/en/prices/)). Bulk download is a genuine strength and
the price fits the budget. **Excluded because the coverage claim on the pricing page is "5,000 US
Stocks"** with no European or UK exchange named, and nothing published about delisted securities,
restatements or filing timestamps. If the pricing page understates non-US coverage, that would be
worth revisiting — but on published information it fails the first-priority criterion.

### Finnhub — excluded (and partly unverifiable)

Finnhub's pricing pages render entirely client-side and could not be read directly; the served HTML
contains only a strapline ([finnhub.io/pricing](https://finnhub.io/pricing),
[pricing-fundamental-data](https://finnhub.io/pricing-fundamental-data)). Figures circulating in
secondary sources — Market Data Basic around $49.99/month, a premium band of roughly
$11.99–$99.99/month adding international stocks, All-In-One at $3,500/month — are **unverified and
should not be relied on**. Finnhub does claim 60+ global exchanges including LSE and "30+ years of
historical fundamentals". **Excluded for the bake-off** on two grounds: the market data and
fundamentals are sold as separate products so the tier actually needed is unclear and plausibly
above budget, and nothing public addresses delisted securities or restatements. Reconsider only if
the two shortlisted providers both fail on UK delisted coverage.

### Norgate Data — excluded

Survivorship-bias-free by design, with delisted securities and historical index constituents (the
latter at Platinum tier and above), which is precisely the property this platform values
([norgatedata.com](https://norgatedata.com/),
[data package FAQ](https://norgatedata.com/data-package-faq.php)). **Excluded because coverage is
US, Canada and Australia only — no UK or European market.** Pricing was not verified (the pricing
page URL guessed from the site structure returned 404) and does not matter given the exclusion.
Also delivered primarily to desktop platforms (AmiBroker, Wealth-Lab) rather than as a REST API,
which would not suit the adapter architecture.

### Polygon.io / Massive — excluded

US equities only. Stocks Starter $29/month, Developer $79–99, Advanced $199, All-Access $399, billed
per asset class; the company rebranded to Massive.com in July 2026 with API and keys unchanged
([polygon.io/pricing](https://polygon.io/pricing)). These figures come from secondary sources and
are **unverified**. Excellent US corporate-action and flat-file bulk infrastructure, no UK coverage,
so excluded on the first-priority criterion.

### Alpha Vantage — excluded

Premium tiers are priced purely by request rate: $49.99 (75 req/min), $99.99 (150), $149.99 (300),
$199.99 (600), $249.99 (1200) per month, with annual equivalents at two months' discount
([alphavantage.co/premium](https://www.alphavantage.co/premium/)). The premium page says nothing
about international equity coverage, delisted tickers or fundamentals depth, and there is no
published delisted or PIT product. Excluded: paying $50/month for rate limit alone, with no
delisted-coverage claim, scores badly on every criterion that matters here.

### Marketstack — excluded

Free / Basic $9.99 / Professional $49.99 / Business $149.99 per month, with 15+ years of history
from Professional and fundamentals only at Business
([marketstack.com/product](https://marketstack.com/product)). Splits and dividends are included at
all tiers. Excluded because delisted coverage is not mentioned anywhere, and because the page states
US data is sourced from Tiingo — buying Marketstack to get UK data would mean buying a reseller's
aggregation with an extra licensing layer and no published PIT capability.

### Twelve Data — not assessed in depth

Claims EOD pricing from 100+ exchanges with personal (non-commercial) and business plan families
([twelvedata.com/pricing](https://twelvedata.com/pricing)). Current tier prices were not verified
(pricing table is client-rendered). Plausibly relevant on breadth and price, but nothing public
found on delisted securities, restatements or filing timestamps, so it does not displace either
shortlisted provider. Recorded as a fallback candidate, not a recommendation.

### LSEG / Refinitiv — excluded on cost

LSEG's Point In Time Fundamentals product is the reference implementation of what this platform
wants: time-stamped financials with original and restated values as they became available
([lseg.com](https://www.lseg.com/en/data-analytics/financial-data/company-data/fundamentals-data/point-in-time-fundamentals)).
There is no self-serve tier and no published individual price; third-party estimates put Workspace
seats in the $1,500–$3,000 per user per month range and Eikon-class packages around $15,000/year
(**unverified**, secondary sources). Two orders of magnitude outside a ~£100/month budget. Recorded
so the shortlist is a comparison against the ideal, not just among the affordable.

### Exchange Data International (EDI) — worth a quote, cannot be priced

London-based reference-data vendor. Claims point-in-time security reference records for 185,000+
listed **and delisted** securities across 200+ exchanges, and a World Corporate Actions feed of 4.5m+
records for 300,000+ securities with history from 2000
([exchange-data.com](https://www.exchange-data.com/product/worldwide-corporate-actions-data/)).
There is a self-serve developer portal with a "start for free" registration and an API playground,
but **no prices are published anywhere on it**
([developer.exchange-data.com](https://developer.exchange-data.com/)).

The reason to record EDI rather than dismiss it: it reportedly **sells** data rather than renting
it, so a client keeps everything received after the contract ends — the one licensing model that is
compatible with a permanent raw-payload archive. That claim came from a secondary summary and is
**unverified**; it is exactly the kind of thing worth an email. Not shortlisted for the bake-off
because a provider with no obtainable price cannot be compared, and the sales cycle is out of scope
for this ticket. **Suggested owner action: request an indicative price for UK equity EOD plus
corporate actions plus delisted reference data on a single-user research licence.**

### Free sources worth wiring in regardless

Neither of these replaces a vendor, but both are free, permanently retainable, and better than any
paid candidate on the criterion they cover:

- **SEC EDGAR** — full-text filings with acceptance timestamps to the second, no licence
  restriction on retention. This is the ground truth against which any vendor's US `acceptedDate`
  should be checked in QNT-035.
- **Companies House and LSE RNS** — UK filing and announcement dates. Since no affordable vendor
  offers UK announcement timestamps, an RNS-derived announcement date is likely to be the only
  honest basis for a UK `available_at` that is not a conservative imputation from period end.

### Recommendation

> **OWNER DECISION GATE — nothing is purchased without the owner's sign-off.** This section names
> what to buy and what it costs; it does not authorise buying it. QNT-031…033 stay blocked on API
> keys until the owner signs off, and a `DECISIONS.md` entry recording the choice is part of that
> sign-off. Re-verify every price on the day of purchase.

Buy in two phases rather than all at once, because the second phase is only needed if the first
fails, and because both licences forbid keeping data after cancellation — so running two paid
providers simultaneously buys nothing that running them consecutively does not.

**Phase 1 — EODHD ALL-IN-ONE, €99.99/month month-to-month (~£85).** First because it is the only
candidate that covers UK EOD prices, corporate actions, delisted securities and fundamentals under
one subscription, its delisted data is documented at a per-endpoint level rather than gestured at,
and it sources UK data from LSE directly. Buy month-to-month, not the €999.90 annual commitment,
until the bake-off has run. *Main uncertainty:* whether LSE delisted coverage actually exists —
`exchange-symbol-list/LSE?delisted=1` is the single highest-value call in the whole bake-off, and
every delisted example in EODHD's documentation is American. Secondary uncertainty: non-US
fundamentals start in 2000, so pre-2000 UK research is out of reach at this tier regardless of how
well it scores. If the cheaper All-World + Fundamentals Feed combination (€79.98) turns out to be
purchasable concurrently, take it and save ~£17/month.

**Phase 2 — FMP Premium, $59/month if billed annually (~£44); month-to-month price unverified.**
Second because it is the only candidate with a to-the-second announcement timestamp in its schema,
which is the platform's hardest data requirement, and because UK coverage starts at Premium rather
than being absent. Run it alongside a downgraded EODHD All-World EOD subscription (€19.99, ~£17) so
Phase 2 stays inside budget at roughly **£61/month**. *Main uncertainty:* whether any of FMP's UK
data carries the filing timestamps its US data does — if `acceptedDate` is null outside the US, the
main reason to pay for FMP evaporates and Phase 2 should stop after one month. Also unresolved:
FMP's §2.2.1 "may not copy or download any content" clause versus normal API use, which should be
put to FMP in writing before the card comes out.

**Third: Tiingo Starter at £0.** Build the QNT-033 adapter against the free tier and use it as an
independent US cross-check. Do not buy Power — Tiingo has no LSE coverage, which makes it the wrong
purchase at any price for this platform.

| Phase | Subscriptions | Monthly cost |
| --- | --- | --- |
| Phase 1 (month 1) | EODHD ALL-IN-ONE + FMP Basic (free) + Tiingo Starter (free) | €99.99 ≈ **£85** |
| Phase 2 (month 2, only if Phase 1 leaves the UK/PIT questions unanswered) | EODHD All-World EOD + FMP Premium | €19.99 + $59 ≈ **£61** |
| Peak monthly spend | — | **~£85**, inside the ~£100 budget |

Two consequences the owner should agree to before signing off:

1. **The raw-payload archive is licensed, not owned.** Cancelling EODHD obliges deletion within one
   month; cancelling FMP obliges immediate deletion plus a signed certificate. Whatever the bake-off
   concludes, the winning provider's subscription has to be maintained for the archive to remain
   lawful, and the losing providers' raw payloads must be deleted when their subscriptions end. The
   bake-off's durable evidence should therefore be the derived check results and scores, not the
   raw payloads, for any provider that is not retained — which is a change to what QNT-036 persists
   and should be recorded as an architecture exception per `docs/ARCHITECTURE.md`.
2. **True PIT fundamentals are not purchasable at this budget.** Announcement timestamps for UK
   issuers will have to be imputed conservatively (QUANT_PRINCIPLES §1) or sourced from RNS, and no
   candidate offers restatement history. The bake-off should score PIT availability honestly rather
   than grading on a curve — expect the winner to score poorly here, and expect that to be correct.

## Results

*(generated section — empty until QNT-036 runs)*
