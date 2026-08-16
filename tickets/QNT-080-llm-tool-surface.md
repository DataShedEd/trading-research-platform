# QNT-080 — Deterministic tool surface for LLM

- **Ticket ID:** QNT-080
- **Status:** BACKLOG
- **Priority:** P3
- **Epic:** EPIC 14 — LLM Research Interface

## Problem
A language model given a natural-language question about a portfolio will produce a confident,
well-formatted, plausible answer whether or not it has the data to support one. Applied to
quantitative research this is worse than useless: an invented Sharpe ratio or a hallucinated revenue
figure is indistinguishable in tone from a correct one. `VISION.md` therefore requires the model to
invoke deterministic platform functions rather than calculate anything itself, which means the tool
surface — not the prompt — is where the guarantee has to live.

## Objective
Define a typed tool surface over platform queries that the model calls to obtain every number it
reports, with the tool contracts making an unsupported question fail rather than be answered.

## Scope
`trp.llm.tools`: typed tool/function definitions covering security lookup, price and fundamental
queries, factor scores and rankings, universe membership, backtest and experiment retrieval, and
portfolio risk; schema generation for the tool definitions; a dispatcher validating arguments and
invoking the corresponding research API operation; structured tool results including provenance.

## Out of scope
Prose generation and explanation rendering (QNT-081); guardrail tests and evaluation (QNT-082);
model provider selection and prompt engineering beyond what the tool contracts require; any tool
that mutates state or places an order.

## Acceptance criteria
- [ ] Every tool is defined by a typed schema generated from the same models the research API uses,
      so a tool cannot describe a parameter the API does not accept.
- [ ] Every tool that reads historical data requires `as_of`, and the dispatcher rejects a call
      missing it rather than supplying a default.
- [ ] Tool results are structured data carrying units, currency, estimation parameters and definition
      versions; no tool returns a pre-formatted sentence.
- [ ] The tool set contains no arithmetic or aggregation tool: there is no way for the model to ask
      the platform to "calculate" something the platform does not already define, and a test
      enumerates the tool list to assert this.
- [ ] Invalid arguments produce a structured error the model can act on, and unavailable data returns
      an explicit not-available result rather than an empty success.

## Technical notes
The distinction between "no data" and "zero" matters more here than anywhere else in the platform,
because a model shown an empty result will often narrate it as an absence of exposure. Not-available
must be a distinct, unambiguous result type.

Tools call the research API operations (QNT-074) rather than reaching into `trp` directly, so the
model is subject to the same `as_of` and provenance requirements as every other consumer.

## Dependencies
QNT-074 — the research endpoints the tools are defined over.

## Risks
Tool sprawl weakens the guarantee: a general-purpose query tool would let the model construct its own
calculations and reintroduce exactly the failure mode this epic exists to prevent. Mitigated by the
enumerated-tool-list test and by keeping every tool a named platform operation.

## Testing requirements
`tests/llm/test_tools.py`: schema-versus-API parameter agreement, `as_of` enforcement, not-available
versus zero distinction, structured error handling, and the no-arithmetic-tool enumeration assertion.

## Documentation requirements
`docs/ARCHITECTURE.md` gains the `trp.llm` package and states the rule that the model invokes
deterministic functions and computes nothing; the tool list documented with each tool's provenance
fields.

## Completion notes
_Not started._
