# Research methodology

Investment research here is run as experiments. The unit of research is not a notebook or a
backtest run — it is a recorded experiment testing a stated hypothesis. Epic 10 builds the
registry; this document defines the discipline it encodes.

## The four artefacts

Keep these distinct and never conflate them:

- **Hypothesis** — a falsifiable statement written *before* looking at results. Example: "Among
  UK large- and mid-cap equities, securities with strong medium-term momentum, high
  profitability and positive earnings revisions generate positive subsequent risk-adjusted
  excess returns."
- **Experiment** — one concrete parameterisation: universe, observation period, holding period,
  signal and factor definitions (by version), entry/exit rules, portfolio construction,
  transaction-cost assumptions, benchmark.
- **Evidence** — the metrics an experiment produced, with everything needed to reproduce them
  (git commit, data versions, parameters, seed).
- **Conclusion** — an explicit judgement referencing evidence, including weaknesses and
  follow-up experiments. A conclusion may be "inconclusive".

## Rules

1. Write the hypothesis and the experiment design down before running it. Post-hoc hypotheses
   are labelled as exploratory, not confirmatory.
2. Every experiment is reproducible from its record alone (see `QUANT_PRINCIPLES.md` §4).
3. Count your shots: the registry tracks how many variants of a hypothesis were tried.
   Many-variant searches require out-of-sample or holdout confirmation before any conclusion
   stronger than "worth a confirmatory test". Be honest about multiple-hypothesis testing —
   a 1-in-20 p-value found on the 20th attempt is noise.
4. Prefer fewer parameters. Any parameter chosen by optimisation must be reported with its
   sensitivity (does performance survive ±50% perturbation?).
5. Costs are part of the strategy. Default assumptions err pessimistic (UK: stamp duty 0.5% on
   purchases, plus spread and commission); an experiment that only works with optimistic costs
   has failed.
6. Benchmark must match the universe (UK mid-cap strategy → FTSE 250-type benchmark, total
   return, same currency).
7. Report regime dependence: results shown per sub-period, not just full-sample. A strategy
   that worked only 2009–2014 is a regime observation, not a discovery.
8. When a methodological choice could flatter results (universe tweak, exclusion, date range,
   winsorisation change), document it in the experiment record at the time it is made.

## Workflow

hypothesis → design → (registry entry) → run → evidence persisted → conclusion + weaknesses →
follow-ups become new registry entries. Failed experiments are kept forever; they are the
denominator that keeps the successes honest.
