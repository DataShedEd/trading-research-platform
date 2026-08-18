# Quantitative principles (non-negotiable)

These constraints override convenience, performance, and delivery speed. Any code or research
that violates them is wrong even if its output looks right.

## 1. Point-in-time correctness

Historical research may only access information actually available at the simulated date.

- Every canonical fundamental record carries: security identifier, reporting period end,
  filing/publication timestamp, **first-known timestamp** (`available_at`), revision/restatement
  timestamp, source, and value.
- Every historical query API takes an explicit `as_of` parameter and must never return rows with
  `available_at > as_of`.
- Where a provider gives no announcement timestamp, we impute one **conservatively** (late, not
  early — e.g. period end + a documented reporting lag) and record that it was imputed.
- `tests/timetravel/` holds tests (pytest marker `timetravel`) that fail if future information
  becomes visible; every data-access feature ships with one.

Backtest-layer enforcement: the QNT-057 leakage suite (tests/timetravel/test_backtest_leakage.py) proves as-of monotonicity differentially — a store extended with later-dated data reproduces every run byte-identically — and its negative control shows a same-day-clock engine is caught by the scenarios.

## 2. Survivorship bias

Historical universes are never constructed from current index membership or currently listed
securities.

- Delisted, bankrupt, acquired, and renamed securities are first-class data, retained forever.
- Ticker and identifier changes are modelled with effective date ranges; the internal
  `security_id` is immutable and never reused.
- Universe membership is time-indexed: `members("FTSE350", date)` reads historical constituent
  data, never today's list.

## 3. Corporate actions

Prices and returns must correctly handle splits, dividends, special dividends, rights issues
(where data permits), mergers/acquisitions, delistings, and ticker changes.

- Raw (as-traded) and adjusted values are both stored and always distinguishable.
- Adjustment factors are data derived from corporate-action records — never in-place mutation of
  price history.
- Total returns include dividends; delisting proceeds (or zero on failure) flow into backtest
  accounting rather than the position silently vanishing.

Backtest-layer enforcement: QNT-057's hand-computed scenarios (tests/backtest/test_scenarios.py) assert dividends credit once at ex-date, splits move nothing, and delistings resolve to proceeds or a write-off, with costs reconciling exactly against the ledger in every scenario.

## 4. Reproducibility

Every research result must be reproducible from what is persisted: git commit, dataset
version/ingestion timestamps, universe definition, factor definitions and versions, rebalance
rules, transaction-cost assumptions, parameters, exclusions, benchmark, random seed where
relevant, and output metrics. If a result cannot be regenerated, it is not evidence.

## 5. Research safeguards

Actively guard against: look-ahead bias, survivorship bias, selection bias, data snooping,
overfitting, excessive parameter optimisation, unrealistic transaction costs, ignored market
impact, benchmark mismatch, multiple-hypothesis testing, and regime-specific results presented
as universal. Whenever a methodological choice could materially flatter historical performance,
document it in the experiment record and in `RESEARCH_METHODOLOGY.md`. When in doubt, choose the
assumption that makes the strategy look worse.
