# QNT-082 — LLM guardrails and evaluation

- **Ticket ID:** QNT-082
- **Status:** BACKLOG
- **Priority:** P3
- **Epic:** EPIC 14 — LLM Research Interface

## Problem
The tool surface and the verification step constrain what the model can say, but neither is tested
against the questions it will actually be asked — including the ones it should refuse. A model asked
"will this stock go up?" or "what were the 2019 earnings?" for a security with no fundamentals
coverage will, unguarded, produce an answer. And because model behaviour changes with every version
and prompt edit, a guarantee that is not re-measured is a guarantee that has already expired.

## Objective
Establish the guardrail tests and a maintained evaluation set that measure, on every change, whether
answers cite only platform-computed values, whether unsupported questions are refused, and whether
known questions get known answers.

## Scope
`tests/llm/`: a curated evaluation set of question/expected-answer pairs over fixture data covering
answerable, unanswerable and out-of-scope questions; assertions on citation of platform values;
refusal behaviour for forecasts, advice and unavailable data; a scored evaluation run reporting pass
rate per category; documentation of the thresholds required before the interface is used.

## Out of scope
Model fine-tuning; adversarial or jailbreak testing beyond the categories listed; latency and cost
benchmarking; changing the tool surface, which is QNT-080.

## Acceptance criteria
- [ ] The evaluation set covers, at minimum: answerable factual questions, questions about data the
      platform does not hold, forecast questions, advice-seeking questions, and questions whose
      answer requires a calculation the platform does not define.
- [ ] Every answer in an evaluation run is checked to contain only figures traceable to tool results,
      reusing the QNT-081 verification, and any unverifiable figure fails the run.
- [ ] Unanswerable, forecast and advice questions are refused with an explanation of why, and refusal
      rate for those categories is reported per run with a documented required threshold.
- [ ] The evaluation runs as a distinct, separately invoked suite (not part of `make check`, since it
      calls a model), and its results including the model version are recorded per run.
- [ ] A regression in any category against the last recorded run is reported as a failure rather than
      as a changed number.

## Technical notes
Record the model identifier and version with every evaluation run: an unchanged pass rate across a
model change is information, and a changed one is a reason to look before shipping. Treat the
evaluation set as an asset that grows — every real question that produced a bad answer becomes a new
case.

Refusal must be specific. "I cannot answer that" is less useful than "the platform holds no
fundamentals for this security before 2015", and the specific form is also easier to test.

## Dependencies
QNT-080 — the tool surface whose behaviour is being evaluated.

## Risks
An evaluation set small enough to be cheap is also small enough to be unrepresentative, and passing it
can create unearned confidence; mitigated by growing it from real failures and by reporting per-category
rates rather than a single aggregate number.

## Testing requirements
This ticket is the testing requirement; it is complete when the suite runs on demand, records results
with model versions, and fails on category regression.

## Documentation requirements
Evaluation categories, thresholds and the run procedure documented alongside the suite; a note in
`docs/ARCHITECTURE.md` that the LLM interface is gated on this evaluation rather than on review alone.

## Completion notes
_Not started._
