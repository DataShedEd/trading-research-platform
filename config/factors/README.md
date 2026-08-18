# Factor definitions

Each `*.json` file here is one immutable version of one factor. The framework
(`trp.factors`) loads them all at registry construction and rejects: duplicate
(name, version) pairs, unknown transform identifiers, unknown input datasets, and —
the important one — **definitions edited in place**.

## Authoring a definition

```json
{
  "name": "momentum_12_1",
  "version": 1,
  "description": "12-1 month total-return momentum",
  "inputs": ["prices", "corporate_actions"],
  "transform": "window_total_return",
  "parameters": {"months": 12, "skip_months": 1, "basis": "total"},
  "content_hash": "<see below>"
}
```

1. Pick the transform from `trp.factors.compute.registered_transforms()` — configuration
   parameterises named Python transforms; it is never a place for expressions.
2. Compute the hash: `uv run python -c "import json; from trp.factors.definition import
   compute_content_hash; print(compute_content_hash(json.load(open('config/factors/yourfile.json'))))"`
   and paste it into `content_hash`.
3. To change a published definition: copy the file, bump `version`, recompute the hash.
   Never edit a published version's body — the registry will refuse to load it, which is
   the point: every stored factor value is tagged `name@version` and must stay
   reproducible forever. `description` is the one cosmetic exception (excluded from the hash).
