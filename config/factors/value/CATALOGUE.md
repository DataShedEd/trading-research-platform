# Value factor catalogue (QNT-046)

Six v1 definitions. Market values are point-in-time on both sides: market cap = raw GBX
close on or before t (DEC-020-repaired source) / 100 x shares outstanding **available at
t** (a later share-count restatement cannot rewrite history — timetravel-tested);
enterprise value adds net_debt from the latest balance sheet available at t, months
stale relative to the price by design. Non-GBP statements convert at the dated FX rate
on or before t (`trp.canonical.fx`, GBPUSD/GBPEUR; a stale or missing rate refuses as
no_data rather than inventing one).

| Factor | Formula | Form | Refusals |
|---|---|---|---|
| earnings_yield | net_income_GBP / market cap | yield (negative earnings rank naturally) | mcap <= 0 |
| fcf_yield | free_cash_flow_GBP / market cap | yield | mcap <= 0 |
| ebit_ev_yield | ebit_GBP / enterprise value | yield form of EV/EBIT | EV <= 0 |
| ebitda_ev_yield | ebitda_GBP / enterprise value | yield form of EV/EBITDA | EV <= 0 |
| book_to_market | total_equity_GBP / market cap | ratio | negative book value (documented exclusion) |
| shareholder_yield | -(dividends_paid + share_buybacks)_GBP / market cap | yield; window = latest reported year; positive = cash returned, net issuance negative | mcap <= 0 |

Availability-lag sensitivity: these factors inherit DEC-007's conservative imputation
end-to-end; shortening the lag flatters results and is not a local decision.

Real-data cross-section (FTSE 100 at 2020-06-30): 94-99/100 computable; medians
earnings yield 5.2% (P/E ~19), book-to-market 0.44, EBITDA/EV 9.5%, shareholder yield
4.8% — all in FTSE territory.
