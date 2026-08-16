# QNT-081 — Signal explanation service

- **Ticket ID:** QNT-081
- **Status:** BACKLOG
- **Priority:** P3
- **Epic:** EPIC 14 — LLM Research Interface

## Problem
"Why is this ranked highly?" is the question that decides whether a systematic process is trusted or
quietly overridden. The factor decomposition already answers it numerically, but a table of z-scores
and weights is not an explanation anyone reads carefully at the point of decision. Turning it into
prose is genuinely useful and genuinely dangerous: the moment the language model supplies a number
the platform did not compute, the explanation becomes fiction with a citation-shaped surface.

## Objective
Provide an explanation service that renders the factor-decomposition payload into prose, where every
figure in the output is drawn from the platform-computed payload and the mapping from figure to source
is checkable.

## Scope
`trp.llm.explain`: assembly of the explanation payload for a security's signal (composite score, rank,
contributing factors with scores, percentiles, versions and weights, universe and as-of date), prose
rendering via the model, and a verification step checking every numeric token in the output against
the payload before the explanation is returned.

## Out of scope
Investment advice or recommendations; explanations of backtest results or portfolio performance;
guardrail test suites and evaluation sets (QNT-082); the terminal's presentation of explanations.

## Acceptance criteria
- [ ] Explanations are generated only from a payload assembled by platform code; the model receives no
      free-text data source and no ability to fetch beyond the QNT-080 tools.
- [ ] Every numeric value in the generated prose is present in the payload within a documented
      rounding tolerance, verified automatically before the explanation is returned; verification
      failure returns an error rather than the prose.
- [ ] Explanations state the as-of date, the universe and the factor definition versions used.
- [ ] Where a contributing factor is missing for the security, the explanation says so explicitly
      rather than describing the composite as though the factor were neutral.
- [ ] Explanations contain no recommendation to buy, sell or hold, asserted by a test over the
      evaluation examples.

## Technical notes
The numeric verification step is the substance of this ticket: extract numeric tokens from the
generated text and match each against the payload, allowing for stated rounding and formatting. It is
crude and it works, and it converts "the model was told not to invent numbers" into a property that
is checked on every response.

Rank and percentile are relative to a stated universe on a stated date; an explanation that omits
either is ambiguous enough to be wrong, so both are required payload fields.

## Dependencies
QNT-080 — the deterministic tool surface and payload contract the explanation is built from.

## Risks
Fluent prose is trusted more than a table, so an unverified explanation would carry more weight than
the numbers it misreports; mitigated by the mandatory verification step and by failing closed when
verification does not pass.

## Testing requirements
`tests/llm/test_explain.py`: payload assembly correctness, verification catching an injected
fabricated number, missing-factor wording, absence of recommendation language, and required
provenance fields in the output.

## Documentation requirements
The verification rule and its tolerance documented in the module docstring; a note in
`docs/ARCHITECTURE.md` that explanations fail closed on verification failure.

## Completion notes
_Not started._
