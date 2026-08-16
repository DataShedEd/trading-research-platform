# Data provider evaluation

Status: **framework defined; empirical evaluation not yet run.** Candidates: EODHD, Financial
Modeling Prep (FMP), Tiingo, plus any discovered during research (QNT-028). This document is
partly generated: the scoring tables below will be produced by the bake-off harness
(`trp.bakeoff`, QNT-036) from real API responses — never from advertised feature lists.

## Method

We do not trust marketing pages. Each candidate is exercised against a deliberately awkward
**validation universe** (defined in QNT-027, versioned in the repo) containing, at minimum:

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

Weights defined in QNT-030; all scores computed, with links to the raw evidence.

| Criterion | What the harness measures |
| --- | --- |
| Historical depth | Earliest usable price/fundamental data per market |
| Delisted coverage | Fraction of validation-universe delistings present with data to delisting date |
| Corporate-action accuracy | Splits/dividends match known-correct fixtures (dates, ratios, amounts) |
| Identifier stability | ISIN/SEDOL presence; behaviour across ticker changes |
| PIT fundamental availability | Announcement timestamps present? First-known reconstructible? |
| Revision history | Are restatements visible as distinct records? |
| API reliability | Error rates, latency, consistency across repeated pulls |
| Rate limits & bulk | Documented vs observed limits; bulk download paths |
| Licensing | Storage/redistribution constraints on raw payload retention |
| Cost | Actual tier needed for the above, per month |

## Provider notes and pricing

To be filled by QNT-028 (research report, with current pricing verified at time of writing) and
QNT-031…035 (empirical results). Purchasing a subscription is an owner decision; the research
report is the input to it.

## Results

*(generated section — empty until QNT-036 runs)*
