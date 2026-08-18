# Tearsheet — momentum-12-1-ftse100-monthly-to-2026-08-17

**This is an infrastructure proof, not a research conclusion** (RESEARCH_METHODOLOGY
rules 3 and 7 apply before any claim is made from one configuration).

## Configuration

| | |
|---|---|
| Factor | momentum_12_1 v1 |
| Universe | FTSE100 (survivorship-free, QNT-041 gate) |
| Period | 2010-01-01 to 2026-08-17 |
| Rebalance | monthly, offset 0 |
| Selection / weighting | top 20, equal |
| Initial capital | 100,000,000 GBX (£1,000,000) |
| Costs | 2 bps commission (min 500 GBX), 10 bps spread, 50 bps stamp (buys), impact 25 bps x participation |
| Config hash | `97af396dccde9fd7` |
| Git commit | `710f3d060c225a3f586ff672238fb319824c22df` |
| Run record | `data/derived/backtests/momentum-12-1-ftse100-monthly-to-2026-08-17` |

## Headline metrics

| Metric | Value |
|---|---|
| Total return | +460.20% |
| CAGR | +10.90% |
| Annualised volatility | +19.20% |
| Sharpe (rf = 1.37%) | 0.56 |
| Sortino | 0.84 |
| Max drawdown | -37.80% (trough 2020-03-23) |
| Calmar | 0.29 |
| Hit rate (days) | +53.88% |
| Hit rate (positions) | +52.44% |
| Final value | 557,021,035 GBX (£5,570,210) |
| Total costs paid | 103,814,865 GBX (£1,038,149) |
| Mean one-way turnover per rebalance | 25.9% |
| Rebalances / trades | 200 / 4818 |

## Relative to benchmark

Benchmark: **isf-xlon-tr** — etf_total_return (distributing share class, dividends reinvested at ex-date close).

| Metric | Value |
|---|---|
| Benchmark total return | +251.71% |
| Benchmark CAGR | +7.84% |
| Excess CAGR (geometric) | +2.86% |
| Tracking error | 12.20% |
| Information ratio | 0.28 |

## Annual returns

| Year | Return |
|---|---|
| 2010 | +19.55% |
| 2011 | -9.67% |
| 2012 | +19.62% |
| 2013 | +36.11% |
| 2014 | +6.84% |
| 2015 | +11.01% |
| 2016 | +34.30% |
| 2017 | +10.63% |
| 2018 | -14.41% |
| 2019 | +22.68% |
| 2020 | -7.06% |
| 2021 | +3.19% |
| 2022 | -11.02% |
| 2023 | +8.42% |
| 2024 | +8.51% |
| 2025 | +58.40% |
| 2026 | +8.28% |

## Rolling windows (regime dependence)

| Window | Worst return | Median | Best | Sharpe min/max |
|---|---|---|---|---|
| 12m | -25.6% (to 2020-03-23) | +9.8% | +69.5% (to 2026-04-09) | -1.24 / 3.51 |
| 36m | -25.4% (to 2020-03-23) | +38.9% | +107.0% (to 2026-06-01) | -0.57 / 1.66 |

Full series: `rolling.parquet` in the run record. All configured windows are reported together (QNT-056).

## Flags

- none

## Conventions and caveats

- Coverage starts 2010-01-01 (DEC-014); ~2.5% of member-months have enumerated data gaps
  (DEC-016) whose absent names are mostly acquisition exits — their missing final run-ups
  would generally have HELPED momentum, so the bias direction is conservative.
- Decisions use the previous session's knowledge; fills at the rebalance close; dividends
  credit on ex-date; unknown delistings write off (DEC-017).
- No delisting/merger records are canonicalised yet, so departures exit via DEC-019 forced
  exits at the last traded close (10 of them; 288 warnings total).
- Risk-free rate: mean UK 3-month gilt yield 2010-01-01..2026-08-17 (UK3M.GBOND, EODHD), 4382 observations; window-mean constant is a documented approximation.
- Position construction rules per DEC-018.
- Prices/dividends/splits are the DEC-020 unit-repaired datasets (EODHD's GBX/GBP
  inconsistencies detected and normalised; evidence in unit_repair_report.json).
