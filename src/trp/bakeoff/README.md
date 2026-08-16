# Bake-off harness

Compares data providers against the validation universe (`universe/`) with persisted,
reproducible evidence. See `docs/DATA_PROVIDER_EVALUATION.md` for the method and the
criteria; `weights.json` for the pre-registered scoring weights (fixed before any real
provider result existed — change only with a versioned justification).

## Running

```sh
uv run python -m trp.bakeoff --run-id first-run --provider eodhd            # full matrix
uv run python -m trp.bakeoff --run-id uk-prices --provider eodhd \
    --market uk --dataset prices --dataset corporate_actions               # subset
uv run python -m trp.bakeoff --run-id first-run --provider eodhd --resume  # continue
```

Raw payloads land under `data/raw/<provider>/…` (append-only, verbatim); results under
`data/derived/bakeoff/<run_id>/` (`metadata.json` + `cells.jsonl`, never overwritten).
Re-running with payloads already in the raw store replays from disk — checks re-run
without spending API quota. Reproducing a published result = same universe version +
same raw payloads + `load_run` + `score_provider`.

## Writing a check

Subclass `checks.Check`: set `name`, `criterion` (links results to the scoring rubric),
`datasets`, optionally `properties` (awkward properties it applies to; `None` = all),
implement `run(entry, payloads) -> list[Finding]`, and call `checks.register(...)`.
Findings carry expected/observed/explanation — evidence a reader can adjudicate, not a
bare boolean. Return `NOT_APPLICABLE` when the entry doesn't exercise your case (it is
excluded from scoring denominators); raising inside `run` becomes an `error` result with
traceback, never a crashed run.

## The check inventory (QNT-034/035)

Checks parse raw payload bytes via the **neutral payload convention** (`payloads.py`,
`neutral-1`): a documented JSON shape adapters must emit or approximate — real adapters
may require the parsers to adapt, and the first real run should be treated as validation
of both. Registered checks and the criterion each informs:

| Check | Criterion | Notes |
| --- | --- | --- |
| `split_ratio_and_ex_date` | corporate-action accuracy | exact ratio, exact ex-date |
| `dividend_amount_and_ex_date` | corporate-action accuracy | amount + unit + ex-date |
| `raw_vs_adjusted_consistency` | corporate-action accuracy | where both series present |
| `price_continuity_across_ticker_change` | corporate-action accuracy | no gap/jump at change |
| `delisted_price_history` | delisted coverage | prices up to the delisting date |
| `price_history_depth` | historical depth | long-lived entries only |
| `fundamental_timestamp_presence` | PIT fundamentals | fraction of statements with filed_at |
| `fundamental_timestamp_plausibility` | PIT fundamentals | filed_at after period end etc. |
| `fundamental_availability_class` | PIT fundamentals | observed vs imputable availability |
| `filing_lag_distribution` | PIT fundamentals | evidence for DEC-007 lag parameters |
| `restatement_visibility` | revision history | original AND restated visible, or latest-only |

Facts flagged `needs_verification` in the universe never produce a hard FAIL on their own —
a mismatch is reported as needing expectation review first (see `universe/README.md`).

## Regenerating the comparison report (QNT-036)

The `## Results` section of `docs/DATA_PROVIDER_EVALUATION.md` is generated, never
hand-edited (everything between the heading and the end marker is replaced; prose goes
above or below). From a completed run:

```sh
uv run python -m trp.bakeoff.report --run-id <id> [--provisional]
```

or programmatically: `load_run` → `score_provider` per provider → `render_report` →
`update_results_section`. Reading the table: `unmeasured` means no applicable check ran
(excluded, total renormalised); a zero annotated "not offered" is a capability gap, which
is worse; `coverage` is how many check results informed the score — read a 3-check score
accordingly; veto flags (DEC-012) appear first and override any total. Renders from test
or fake data must carry the provisional banner.
