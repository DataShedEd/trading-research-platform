# Validation universe

`validation_universe.json` is the versioned, authoritative list of deliberately awkward
securities the provider bake-off is scored against (see
`docs/DATA_PROVIDER_EVALUATION.md`). The loader (`loader.py`) validates it strictly:
ISIN/SEDOL check digits, closed property enumeration, source + verification date on every
fact, lifecycle consistency (no event after a delisting), deterministic key ordering.

## Standard of evidence

An expected fact is a claim the harness will score providers against, so a wrong fact is
worse than none. Rules:

1. **Every fact names its source** — prefer primary (RNS announcement, prospectus,
   exchange notice, filing) with enough detail that a reader can re-verify without
   repeating the research — and the date it was verified.
2. **`needs_verification: true`** marks facts whose precision was not fully confirmed
   against a primary source at authoring time (exact ex-dates, ISINs recalled rather than
   looked up). These MUST be re-verified before the fact is used to score a provider;
   the harness should treat disagreement on such facts as an investigation, not a
   provider failure.
3. **Unknown identifiers are recorded as `null`**, never omitted — the gap is data (can
   the provider fill it?).
4. **UK amounts state their unit** (`GBX` vs `GBP`) explicitly; an expectation without a
   unit is untestable.
5. **Bump `version`** on any change; bake-off results are tied to the universe version
   that produced them.

## Adding an entry

Add the entry in key-sorted position, run
`uv run pytest tests/bakeoff/test_validation_universe.py`, and ensure at least one fact
is mechanically checkable. Precision beats breadth: a handful of exact, sourced
expectations discriminates between providers better than dozens of approximate ones.
