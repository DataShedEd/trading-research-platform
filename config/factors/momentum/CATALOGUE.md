# Momentum factor catalogue

All variants use total returns (reinvestment convention, QNT-043) computed strictly
point-in-time — window endpoints resolve to bars on-or-before their dates, and corporate
actions published after the computation's `as_of` are invisible. The shipped set is
deliberately small and conventional (RESEARCH_METHODOLOGY rule 3: momentum windows are
cheap to generate and searching over them is data snooping).

| Factor | Version | Window | Skip | Basis | Transform | Notes |
| --- | --- | --- | --- | --- | --- | --- |
| `momentum_12_1` | v1 | 12 months | 1 month | total | `window_total_return` | The classic; skip excludes short-term reversal |
| `momentum_6_1` | v1 | 6 months | 1 month | total | `window_total_return` | Medium-term variant |
| `momentum_3_0` | v1 | 3 months | none | total | `window_total_return` | Short window, reversal-exposed by design |
| `momentum_12_1_vol_adjusted` | v1 | 12 months | 1 month | total | `window_return_over_volatility` | Return ÷ annualised realised vol (√252) over the same window; near-zero vol → insufficient-data |

Version history: all v1, introduced 2026-08-18 (QNT-044). To change any definition,
copy the file, bump the version, recompute the hash — see `config/factors/README.md`.
