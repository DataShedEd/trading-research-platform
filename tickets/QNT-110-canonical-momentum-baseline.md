# QNT-110 — Canonical momentum baseline: frozen result, full research report, diagnostics

- **Ticket ID:** QNT-110
- **Status:** DONE
- **Priority:** P1
- **Epic:** EPIC 10 — Experiment Registry
- **Depends on:** QNT-107, QNT-108, QNT-109, QNT-102 (DONE)

## Problem
momentum-baseline (EXP-b99d3f65) exists as the QVM control — completed, reproducible,
never concluded, reported only as a tearsheet. The platform's first canonical
single-factor result deserves the full treatment: frozen baseline, complete research
report, robustness diagnostics (never promoted), concentration analysis, and an honest
verdict on whether the research engine is trustworthy.

## Objective
Answer: "do we possess a trustworthy research engine, and what does the simplest
properly controlled UK momentum experiment actually tell us?"

## Scope
- Baseline = the existing pre-registered momentum-baseline config (PIT FTSE 100,
  2010→2026-08-17, momentum_12_1 v1, monthly, top 20 ≈ quintile, equal weight, ISF
  benchmark, DEC-017 execution, shipped costs). No parameter changes after seeing
  results except documented corrections.
- Registered under a new momentum-premium hypothesis with the honest caveat that the
  control run's results were already visible (in-sample; pre-registration is partial).
- Extended report per directive §12: definition, performance stats (incl. Sortino,
  Calmar, beta), annual table, rolling 12m/3y/5y, drawdown episodes, portfolio
  behaviour (holdings, turnover, concentration, cash drag, delistings, forced exits,
  DEC-016 encounters), data-quality disclosure.
- Inspectable artefacts (§13): factor rankings and holdings history persisted per
  rebalance alongside the existing equity/events/rebalance records + manifest.
- Robustness diagnostics (§15), labelled, never promoted: 6-1, 12-2, 2x costs, top
  decile, quarterly.
- Concentration (§16): contribution by security and year, ex-top-1 and ex-top-5.
- Sanity check (§14) recorded in the conclusion.

## Acceptance criteria
- [x] Baseline frozen: reproducible run, conclusion recorded with weaknesses (imputed
      DEC-016 missingness, in-sample caveat).
- [x] Report covers every §12 item; artefacts cover every §13 item.
- [x] Diagnostics + concentration reported; no unexplained extraordinary performance.
- [x] Completion verdict delivered (trustworthy / with limitations / not yet).

## Completion notes
- **HYP-0bf74efd** (momentum premium) registered with the honesty caveat IN the
  hypothesis rationale: the identically-configured control's results were visible first,
  so this is in-sample evidence with partial pre-registration. **momentum-canonical**
  (EXP-529cb55a) verified field-identical to momentum-baseline before running; r1
  reproduced the control's metrics EXACTLY (21/21 + all relative fields) and is
  reproducible from its manifest. Concluded SUPPORTED with five recorded weaknesses.
- Result: CAGR 10.69% vs benchmark ~7.9% (excess +2.66%), Sharpe 0.552, Sortino 0.822,
  max DD −37.8%, IR 0.267, TE 12.2%; 11/17 years beat the benchmark.
- **Diagnostics** (exploratory, tagged robustness-diagnostic, never promoted):
  12-2 IR 0.263 (skip width irrelevant), top-decile 0.247, quarterly 0.324 (breadth and
  cadence not load-bearing), **6-1 IR −0.082** (the phenomenon is specific to ~12-month
  formation), **2x costs IR 0.077** (materially cost-sensitive — sloppy implementation
  could consume the premium). momentum-top10-diagnostic r1 recorded non-reproducible
  because a mid-script commit dirtied the tree under its manifest — process error, noted
  honestly; r2 on a clean tree reproduces r1's metrics exactly.
- **Concentration** (concentration.json in the run record): 167 names traded; largest
  contributor Fresnillo at 8.8% of total P&L; top-5 = 32.5%; CAGR ex-top-1 10.2%,
  ex-top-5 8.7% (arithmetic exclusion, documented as a bound). Not a three-lucky-names
  result. Worst single day −10.4%; drawdown years 2011/2018/2020/2022 — the known
  momentum signature, nothing implausibly smooth or suspiciously strong.
- **§12/§13 coverage**: report.html now adds annual table, rolling 1y/3y/5y (+excess),
  drawdown episodes with same-window benchmark DD, portfolio behaviour (holdings,
  turnover, cash drag, delisting counts, forced exits), beta, Calmar, and a data-quality
  section (DEC-014/016/020/023/024/025 disclosures). write_run persists
  holdings.parquet (ledger replay, asserted against the QNT-108 hand ledger);
  factor_rankings are the materialised store (decision dates ARE month-end sessions and
  the assembly is shared code post-QNT-107, golden-validated); the manifest (registry)
  carries experiment/run ids, git commit, config + definition hashes, dataset versions,
  seed, created_at.
- Multiple-testing warning active on HYP-0bf74efd (6 variants, no out-of-sample run) —
  by design; the recorded follow-up is an FTSE 250 out-of-sample experiment.
