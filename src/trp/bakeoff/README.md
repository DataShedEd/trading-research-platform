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
traceback, never a crashed run. QNT-034/035 add the real corporate-action and PIT checks.
