# Quality factor catalogue (QNT-045)

Nine v1 definitions, all resolving fundamentals through the QNT-025 as-of choke point
(DEC-007 conservative availability — UK: period end +120d annual/+90d interim). Each uses
one consistent statement snapshot: the security's latest reporting period holding every
required item, period-end balances (not averages, stated once in
`trp.factors.fundamental`). Statuses are typed: `not_meaningful` (refusal rule fired,
reason in warnings), `no_data`, `insufficient_data` — never NaN or infinity.

| Factor | Formula | Direction | Refusals |
|---|---|---|---|
| roe | net_income / total_equity | higher better | equity <= 0 |
| gross_profitability | gross_profit / total_assets | higher | assets <= 0 |
| operating_margin | operating_profit / revenue | higher | revenue <= 0 |
| fcf_margin | free_cash_flow / revenue | higher | revenue <= 0 |
| cash_conversion | (CFO - net_income) / total_assets | higher (inverse Sloan accruals) | assets <= 0 |
| earnings_stability | -stdev/|mean| of trailing 5 annual net_income | higher | <4 years; mean ~ 0 |
| net_debt_to_equity | net_debt / total_equity | **lower** better; negative = net cash | equity <= 0 |
| net_debt_to_ebitda | net_debt / ebitda | **lower** better | ebitda <= 0 |
| roic | ebit x (1 - tax_expense/pre_tax_profit clamped [0,1]; 0 when pre-tax <= 0) / (equity + net_debt) | higher | invested capital <= 0 |

Known limitations (documented, not hidden):
- **Financial-sector caveat**: leverage and margin metrics are not meaningful for banks
  and insurers, and the platform has no sector reference data yet, so the by-sector
  refusal the ticket calls for CANNOT be applied. Composites (QNT-048) must not lean on
  net_debt_* or margins across financials until sector data lands.
- EODHD is latest-view-only: pre-first-ingestion restatements are invisible
  (RESEARCH_METHODOLOGY fundamentals note).
- Real-data cross-section (FTSE 100 at 2020-06-30): 98-100/100 computable, medians
  ROE 15.2%, gross profitability 19.3%, ROIC 12.0% — FTSE-plausible throughout.
