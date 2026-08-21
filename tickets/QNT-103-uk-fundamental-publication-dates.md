# QNT-103 — UK fundamental point-in-time availability dates from primary sources

- **Ticket ID:** QNT-103
- **Status:** BACKLOG
- **Priority:** P2
- **Epic:** EPIC 4 — Fundamental Data
- **Depends on:** QNT-097 (DONE)

## Problem
EODHD provides no reliable historical publication timestamps for most UK/EU fundamental
records (~99% of UK filing_date values are period-end defaults — DEC-013 consequences).
All UK fundamental availability is therefore DEC-007 conservative imputation
(period_end + 120d annual / + 90d interim). DEC-024 caps the M1 fundamentals claim at
PARTIAL / IMPUTED until observed publication dates exist.

## Objective
Investigate whether actual historical publication/announcement dates can be sourced
independently for UK financial statements, and if so, design the ingestion.

## Scope
Feasibility study FIRST — no large-scale scraping before documenting, per source:
feasibility, licensing/terms, historical coverage (does it reach 2010?), identifier
mapping effort, and expected value. Candidate sources:

- RNS / LSE announcement archives (preliminary results and interim announcements are the
  true market-knowledge instants — typically WEEKS before Companies House filing);
- issuer investor-relations announcement archives;
- Companies House filing history API (free, authoritative, but filing dates lag
  announcement dates materially — usable as an upper bound / DERIVED source);
- other primary or reliably-archived announcement sources.

Target canonical distinction (extends the QNT-020 schema):

```text
period_end
reported_at              # when the issuer announced/filed
available_at             # when the market could know (the load-bearing field, unchanged)
available_at_source      # where the date came from
available_at_quality     # OBSERVED | DERIVED_FROM_PRIMARY_SOURCE | IMPUTED | UNKNOWN
revision_sequence
```

DEC-007 imputation remains the fallback for records no source covers; existing imputed
rows are re-labelled `IMPUTED`, never silently upgraded.

## Acceptance criteria
- [ ] Written feasibility report per candidate source (coverage, licensing, cost, effort).
- [ ] Schema migration plan for availability-quality labelling; DEC entry superseding
      DEC-007's labelling (not its fallback behaviour).
- [ ] Requirement recorded: fundamental-strategy reports must state the proportion of
      observations using OBSERVED vs IMPUTED availability.
- [ ] Go/no-go recommendation to the owner before any bulk collection.

## Completion notes
_Not started._
