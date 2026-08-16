# Vision

A personal quantitative research and trading platform for medium-term systematic equity
investing. Initial geography: UK equities (FTSE 100/250/350 and the broader UK-listed universe),
with US and European equities supported by the same architecture without redesign.

## What the platform must do

1. Ingest and normalise market, fundamental, corporate-action, macro, and eventually alternative
   data from swappable providers.
2. Reconstruct the information set genuinely available to an investor at any historical date.
3. Screen securities and compute versioned factors (momentum, quality, value, profitability,
   volatility, earnings revisions, composites).
4. Backtest strategies free of look-ahead and survivorship bias, with realistic costs.
5. Construct portfolios under risk constraints; compute exposures, volatility, drawdown,
   correlation, beta, concentration, turnover, VaR/ES.
6. Explain why a security or strategy produced a signal.
7. Retain every hypothesis, experiment, parameter set, and result — research is an experiment
   registry, not a pile of notebooks.
8. Eventually: broker connectivity (paper first, then live with strong safeguards) and a
   web-based research terminal, including an LLM interface that invokes deterministic platform
   functions rather than inventing calculations.

## What the platform is not

Not high-frequency or intraday. Not a product for other users. Not a place for clever
infrastructure: simple, inspectable components; single-machine analytics; boring technology.

## Milestones

- **M1 — Trustworthy historical data.** Can we reliably reconstruct historical UK equity data
  without survivorship bias or future information? (Epics 1–6: foundation, security master,
  market data, fundamentals, provider bake-off, universe engine.)
- **M2 — Factor research.** Versioned factors, backtesting engine, risk metrics, experiment
  registry (Epics 7–10).
- **M3 — Portfolio and access.** Portfolio construction, research API, terminal, LLM interface
  (Epics 11–14).
- **M4 — Execution.** Paper trading, then live with safeguards (Epics 15–16).

No milestone starts until the previous one is demonstrably reliable. Factor research on
contaminated data is worse than no research.
