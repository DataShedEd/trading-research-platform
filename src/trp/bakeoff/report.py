"""QNT-036 — the generated Results section of ``docs/DATA_PROVIDER_EVALUATION.md``.

A hand-written comparison table drifts from the results it claims to summarise and offers no
way to tell which numbers came from evidence and which from someone's recollection. This
module renders the Results section from persisted artefacts only — ``load_run`` for the cells
and ``score_provider`` for the scores — and replaces the whole generated region on every run.
Nothing in that region is ever edited by hand; everything outside it is preserved byte for
byte.

## What the section says, and in what order

Per-criterion breakdown first, aggregate second. QNT-030's totals are ordinal: 0.82 versus
0.79 is not a difference, and leading with the total invites a reader to treat it as one. A
provider that fails a veto criterion is flagged at the top of its own section regardless of
its total. What was *not* measured — unsupported datasets, rate-limited cells, errored
checks, unmeasured criteria — is rendered as prominently as what was, because a comparison
that silently omits its gaps is the failure mode this epic exists to avoid.

Measurement findings (:data:`~trp.bakeoff.payloads.MEASUREMENT_PREFIX`, e.g. QNT-035's
filing-lag distribution) are surfaced in their own subsection: they score nothing, and losing
them would waste the most directly actionable output of the whole exercise.

## Determinism

Everything is sorted explicitly, scores render from ``Decimal`` at a fixed three decimal
places, and timestamps render as UTC with an explicit ``Z`` (DEC-005). ``generated_at`` is a
parameter rather than a call to the clock: the CLI passes the *run's* start time, so
regenerating an unchanged run produces byte-identical output and a diff shows only genuine
result changes.

## Provisional renders

``provisional=True`` stamps a banner at the very top of the section. Any render from fake or
test data must set it — a plausible-looking table of scores for a provider nobody has
actually called is the single most misleading artefact this repository could produce.
"""

import argparse
import subprocess
import sys
from collections import Counter
from collections.abc import Mapping, Sequence
from datetime import UTC, date, datetime
from decimal import Decimal
from pathlib import Path

from trp.bakeoff.checks import CheckResult, Criterion, Outcome
from trp.bakeoff.payloads import (
    DECISION_TRIGGER,
    EXPECTATION_REVIEW_PREFIX,
    MEASUREMENT_PREFIX,
)
from trp.bakeoff.results import CellRecord, FetchStatus, RunMetadata, load_run
from trp.bakeoff.scoring import DeclaredScore, ProviderScore, score_provider

RESULTS_HEADING = "## Results"
GENERATED_BEGIN = "<!-- BEGIN GENERATED trp.bakeoff.report (QNT-036) — DO NOT HAND-EDIT -->"
GENERATED_END = "<!-- END GENERATED trp.bakeoff.report -->"

SCORE_QUANTUM = Decimal("0.001")
"""Three decimal places, fixed, so output is stable across runs. The precision is
presentational: these scores are ordinal and the third digit means nothing."""

INCONCLUSIVE_MARGIN = Decimal("0.05")
"""Totals closer than this are not a ranking. The generator says so rather than manufacturing
a winner — an explicit condition, not an accident of formatting."""

MAX_FAILURE_EXAMPLES = 3

_UNMEASURED = "unmeasured"


class ReportError(Exception):
    pass


def _fmt_score(value: Decimal | None) -> str:
    return _UNMEASURED if value is None else f"{value.quantize(SCORE_QUANTUM)}"


def _fmt_time(value: datetime) -> str:
    return value.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def _cell(text: str | None) -> str:
    """Make a string safe to drop into a markdown table cell."""
    if text is None:
        return "—"
    return text.replace("|", r"\|").replace("\n", " ").strip() or "—"


def _provider_cells(cells: Sequence[CellRecord], provider: str) -> list[CellRecord]:
    return [c for c in cells if c.provider == provider]


def _check_results(cells: Sequence[CellRecord]) -> list[CheckResult]:
    return [result for cell in cells for result in cell.checks]


def _is_measurement(result: CheckResult) -> bool:
    return MEASUREMENT_PREFIX in result.explanation


def _weights(score: ProviderScore) -> dict[Criterion, Decimal]:
    return {b.criterion: b.weight for b in score.breakdown}


def _banner(provisional: bool, reason: str) -> list[str]:
    lines = [
        GENERATED_BEGIN,
        "",
        "> **This section is generated.** `trp.bakeoff.report` (QNT-036) rewrites everything",
        "> between the markers from the persisted run results. Hand edits here are lost on the",
        "> next regeneration — change the checks, the weights or the universe instead.",
    ]
    if provisional:
        lines += [
            "",
            "> ⚠️ **PROVISIONAL — GENERATED FROM FAKE/TEST DATA.** These numbers evaluate no real",
            "> provider, were produced without any live API call, and must not inform a purchase",
            f"> decision. {reason}".rstrip(),
        ]
    return lines


def _provenance(
    metadata: RunMetadata,
    cells: Sequence[CellRecord],
    scores: Sequence[ProviderScore],
    *,
    generated_at: datetime,
    git_commit: str | None,
    tiers: Mapping[str, str],
    declared_verified_on: date | None,
) -> list[str]:
    adapters = ", ".join(
        f"`{name}` {version}" for name, version in sorted(metadata.providers.items())
    )
    tier_note = (
        ", ".join(f"`{name}`: {tiers[name]}" for name in sorted(tiers))
        or "not recorded for this run"
    )
    weight_versions = sorted({s.weights_version for s in scores}) or ["n/a"]
    filters = "; ".join(
        f"{key}: {', '.join(values)}" for key, values in sorted(metadata.filters.items()) if values
    )
    rows = [
        ("Run identifier", f"`{metadata.run_id}`"),
        ("Run started", f"`{_fmt_time(metadata.started_at)}`"),
        ("Report generated", f"`{_fmt_time(generated_at)}`"),
        ("Validation universe version", f"`{metadata.universe_version}`"),
        ("Weight-file version", ", ".join(f"`{v}`" for v in weight_versions)),
        ("Adapter versions", adapters or "none"),
        ("Git commit", f"`{git_commit}`" if git_commit else "not recorded"),
        ("Tier tested", tier_note),
        ("Run filters", filters or "none (full matrix)"),
        ("Cells recorded", str(len(cells))),
        (
            "Declared inputs verified",
            f"`{declared_verified_on.isoformat()}`" if declared_verified_on else "not recorded",
        ),
    ]
    lines = ["### Run provenance", "", "| Field | Value |", "| --- | --- |"]
    lines += [f"| {label} | {_cell(value)} |" for label, value in rows]
    return lines


def _summary(scores: Sequence[ProviderScore], cells: Sequence[CellRecord]) -> list[str]:
    lines = [
        "### Summary",
        "",
        "Totals are **ordinal summaries, not verdicts**: two providers within "
        f"{INCONCLUSIVE_MARGIN} of each other are not meaningfully separated, and the "
        "per-criterion breakdown below is the real output. Unmeasured criteria are excluded "
        "from the total and the remaining weights renormalised.",
        "",
        "| Provider | Weighted total | Measured criteria | Unmeasured | Veto failures | Status |",
        "| --- | --- | --- | --- | --- | --- |",
    ]
    for score in _ranked(scores):
        measured = [b for b in score.breakdown if b.score is not None]
        unmeasured = [b for b in score.breakdown if b.score is None]
        vetoed = [b.criterion.value for b in score.breakdown if b.veto_failed]
        status = "**UNSUITABLE (veto)**" if score.unsuitable else "candidate"
        lines.append(
            f"| `{score.provider}` | {_fmt_score(score.total)} | {len(measured)}/"
            f"{len(score.breakdown)} | {len(unmeasured)} | "
            f"{_cell(', '.join(sorted(vetoed)) or 'none')} | {status} |"
        )
    lines += ["", f"Cells recorded across all providers: {len(cells)}."]
    return lines


def _ranked(scores: Sequence[ProviderScore]) -> list[ProviderScore]:
    """Highest total first; ``None`` totals last; provider name breaks every tie."""
    return sorted(
        scores,
        key=lambda s: (s.total is None, -(s.total or Decimal(0)), s.provider),
    )


def _criterion_table(score: ProviderScore, results: Sequence[CheckResult]) -> list[str]:
    by_criterion: dict[Criterion, list[CheckResult]] = {}
    for result in results:
        by_criterion.setdefault(result.criterion, []).append(result)

    lines = [
        "| Criterion | Weight | Kind | Score | Contribution | Checks | Notes |",
        "| --- | --- | --- | --- | --- | --- | --- |",
    ]
    for entry in sorted(score.breakdown, key=lambda b: (-b.weight, b.criterion.value)):
        applicable = [
            r
            for r in by_criterion.get(entry.criterion, [])
            if r.outcome is not Outcome.NOT_APPLICABLE
        ]
        notes: list[str] = []
        if entry.veto_failed:
            notes.append("**VETO FAILED**")
        if entry.unmeasured_reason:
            notes.append(entry.unmeasured_reason)
        if entry.score is None:
            notes.append("excluded from the total; remaining weights renormalised")
        lines.append(
            f"| {entry.criterion.value} | {entry.weight.quantize(SCORE_QUANTUM)} | "
            f"{'declared' if entry.declared else 'empirical'} | {_fmt_score(entry.score)} | "
            f"{_fmt_score(entry.contribution)} | {len(applicable)} | "
            f"{_cell('; '.join(notes))} |"
        )
    return lines


def _evidence_table(results: Sequence[CheckResult]) -> list[str]:
    by_criterion: dict[Criterion, list[CheckResult]] = {}
    for result in results:
        by_criterion.setdefault(result.criterion, []).append(result)
    lines = [
        "#### Evidence behind each empirical score",
        "",
        "| Criterion | Checks | pass | fail | error | n/a |",
        "| --- | --- | --- | --- | --- | --- |",
    ]
    if not by_criterion:
        return [
            "#### Evidence behind each empirical score",
            "",
            "No check results were recorded for this provider.",
        ]
    for criterion in sorted(by_criterion, key=lambda c: c.value):
        entries = by_criterion[criterion]
        counts = Counter(r.outcome for r in entries)
        names = ", ".join(f"`{name}`" for name in sorted({r.check for r in entries}))
        lines.append(
            f"| {criterion.value} | {_cell(names)} | {counts[Outcome.PASS]} | "
            f"{counts[Outcome.FAIL]} | {counts[Outcome.ERROR]} | "
            f"{counts[Outcome.NOT_APPLICABLE]} |"
        )
    return lines


def _failure_examples(
    score: ProviderScore, results: Sequence[CheckResult], limit: int
) -> list[str]:
    """Illustrative failures, selected deterministically.

    Ordering: heaviest criterion first, then criterion name, security key, check name and
    explanation — a documented total order, so the same run always quotes the same examples
    and a changed example means a changed result.
    """
    weights = _weights(score)
    failures = [r for r in results if r.outcome in (Outcome.FAIL, Outcome.ERROR)]
    if not failures:
        return ["#### Example failed checks", "", "None: no check failed for this provider."]
    ordered = sorted(
        failures,
        key=lambda r: (
            -weights.get(r.criterion, Decimal(0)),
            r.criterion.value,
            r.security_key,
            r.check,
            r.explanation,
        ),
    )
    lines = [
        "#### Example failed checks",
        "",
        f"{len(failures)} failing or errored check result(s); the "
        f"{min(limit, len(ordered))} on the heaviest criteria are shown "
        "(tie-break: criterion, security, check name, explanation). Every result, passing or "
        "failing, is in the run's `cells.jsonl` with the same evidence fields.",
        "",
    ]
    for result in ordered[:limit]:
        weight = weights.get(result.criterion, Decimal(0)).quantize(SCORE_QUANTUM)
        lines += [
            f"- **{result.criterion.value}** (weight {weight}) — `{result.check}` on "
            f"`{result.security_key}` / {result.dataset.value} → **{result.outcome.value}**",
            f"  - expected: {_cell(result.expected)}",
            f"  - observed: {_cell(result.observed)}",
            f"  - reading: {_cell(result.explanation)}",
            f"  - raw payload: {_cell(', '.join(f'`{ref}`' for ref in result.raw_refs))}",
        ]
        if EXPECTATION_REVIEW_PREFIX in result.explanation:
            lines.append(
                "  - ⚠️ the *expectation* behind this failure is itself unverified; re-verify it "
                "against a primary source before counting this against the provider"
            )
    return lines


def _measurements(results: Sequence[CheckResult]) -> list[str]:
    measurements = sorted(
        (r for r in results if _is_measurement(r)),
        key=lambda r: (r.check, r.security_key, r.dataset.value),
    )
    if not measurements:
        return []
    triggers = [r for r in measurements if DECISION_TRIGGER in r.explanation]
    lines = [
        "#### Measurements",
        "",
        "Observations recorded by the checks rather than judgements of the provider; they "
        "score nothing (see `trp.bakeoff.payloads.MEASUREMENT_PREFIX`). Each is one line of "
        "observed values; a measurement that contradicts a recorded decision is shown in full.",
        "",
    ]
    if triggers:
        lines += [
            f"**{len(triggers)} measurement(s) contradict a recorded decision** and are quoted "
            "in full below; act on them by superseding the decision, never by editing it.",
            "",
        ]
    for result in measurements:
        lines.append(f"- `{result.check}` on `{result.security_key}`: {_cell(result.observed)}")
        if DECISION_TRIGGER in result.explanation:
            lines.append(f"  - {_cell(result.explanation)}")
    return lines


def _gaps(cells: Sequence[CellRecord], results: Sequence[CheckResult]) -> list[str]:
    statuses = Counter(cell.fetch_status for cell in cells)
    throttles = sum(cell.throttle_events for cell in cells)
    errors = [r for r in results if r.outcome is Outcome.ERROR]
    lines = [
        "#### What was not measured",
        "",
        "| Fetch status | Cells | Datasets affected |",
        "| --- | --- | --- |",
    ]
    for status in FetchStatus:
        count = statuses.get(status, 0)
        if not count:
            continue
        datasets = sorted({c.dataset.value for c in cells if c.fetch_status is status})
        lines.append(f"| {status.value} | {count} | {_cell(', '.join(datasets))} |")
    lines += [
        "",
        f"Throttling events during the run: {throttles}. Checks that errored: {len(errors)}.",
    ]
    if statuses.get(FetchStatus.UNSUPPORTED):
        lines.append(
            "An `unsupported` dataset is a capability gap, scored zero on the criteria that "
            "depend on it — distinct from a criterion nobody measured, which is excluded."
        )
    return lines


def _provider_section(score: ProviderScore, cells: Sequence[CellRecord], limit: int) -> list[str]:
    provider_cells = _provider_cells(cells, score.provider)
    results = _check_results(provider_cells)
    lines = [f"### {score.provider}", ""]
    vetoed = [b for b in score.breakdown if b.veto_failed]
    if vetoed:
        detail = ", ".join(
            f"{b.criterion.value} = {_fmt_score(b.score)}"
            for b in sorted(vetoed, key=lambda b: b.criterion.value)
        )
        lines += [
            f"> **UNSUITABLE — veto criterion failed: {detail}.** DEC-012 makes this decisive "
            "regardless of the weighted total: QUANT_PRINCIPLES §1 and §2 are not averageable.",
            "",
        ]
    lines += [
        f"Weighted total **{_fmt_score(score.total)}** (weights `{score.weights_version}`), "
        f"from {len(results)} check result(s) over {len(provider_cells)} cell(s).",
        "",
    ]
    lines += _criterion_table(score, results)
    lines += ["", *_evidence_table(results)]
    lines += ["", *_failure_examples(score, results, limit)]
    measurements = _measurements(results)
    if measurements:
        lines += ["", *measurements]
    lines += ["", *_gaps(provider_cells, results)]
    return lines


def _recommendation(
    scores: Sequence[ProviderScore], declared: Sequence[DeclaredScore]
) -> list[str]:
    lines = [
        "### Recommendation",
        "",
        "> **OWNER DECISION GATE — nothing is purchased without the owner's sign-off.** This is "
        "a recommendation generated from the scores above, not a decision. Re-verify every "
        "price on the day of purchase and record the choice in `DECISIONS.md`.",
        "",
    ]
    candidates = [s for s in _ranked(scores) if s.total is not None and not s.unsuitable]
    if not candidates:
        lines += [
            "**No candidate is recommendable from this run.** Every provider either failed a "
            "veto criterion or produced no measurable results, so there is nothing to choose "
            "between. Fix the run or widen the field before deciding anything.",
        ]
        return lines
    best = candidates[0]
    if len(candidates) == 1:
        lines += [
            f"**Recommended: `{best.provider}`** (total {_fmt_score(best.total)}) — the only "
            "provider in this run that is both scoreable and not vetoed. A field of one is not "
            "a comparison: treat this as 'nothing disqualifying was found', not as a winner.",
        ]
        lines += _uncertainty(best, declared)
        return lines

    runner_up = candidates[1]
    assert best.total is not None and runner_up.total is not None
    margin = best.total - runner_up.total
    if margin < INCONCLUSIVE_MARGIN:
        lines += [
            f"**Inconclusive.** `{best.provider}` ({_fmt_score(best.total)}) and "
            f"`{runner_up.provider}` ({_fmt_score(runner_up.total)}) are separated by "
            f"{_fmt_score(margin)}, inside the {INCONCLUSIVE_MARGIN} margin these ordinal "
            "scores can support. The generator declines to name a winner; the owner should "
            "decide on the per-criterion breakdown above, not on the totals.",
            "",
        ]
    else:
        lines += [
            f"**Recommended: `{best.provider}`** (total {_fmt_score(best.total)}), ahead of "
            f"`{runner_up.provider}` ({_fmt_score(runner_up.total)}) by "
            f"{_fmt_score(margin)}.",
            "",
        ]
    lines += _separating_evidence(best, runner_up)
    lines += _uncertainty(best, declared)
    return lines


def _separating_evidence(best: ProviderScore, runner_up: ProviderScore) -> list[str]:
    other = {b.criterion: b for b in runner_up.breakdown}
    gaps: list[tuple[Decimal, str]] = []
    for entry in best.breakdown:
        rival = other.get(entry.criterion)
        if entry.score is None or rival is None or rival.score is None:
            continue
        difference = (entry.score - rival.score) * entry.weight
        if difference != 0:
            gaps.append(
                (
                    abs(difference),
                    f"- {entry.criterion.value} (weight "
                    f"{entry.weight.quantize(SCORE_QUANTUM)}): `{best.provider}` "
                    f"{_fmt_score(entry.score)} vs `{runner_up.provider}` "
                    f"{_fmt_score(rival.score)}",
                )
            )
    if not gaps:
        return ["The two are indistinguishable on every commonly measured criterion.", ""]
    ordered = [text for _, text in sorted(gaps, key=lambda g: (-g[0], g[1]))]
    return ["What separates them, heaviest first:", "", *ordered[:3], ""]


def _uncertainty(score: ProviderScore, declared: Sequence[DeclaredScore]) -> list[str]:
    unmeasured = sorted(b.criterion.value for b in score.breakdown if b.score is None)
    cost = next(
        (d for d in declared if d.provider == score.provider and d.criterion is Criterion.COST),
        None,
    )
    lines = [
        "**Main uncertainty:** "
        + (
            f"{len(unmeasured)} criterion/criteria unmeasured for this provider "
            f"({', '.join(unmeasured)}), so the total is renormalised over the rest and says "
            "nothing about them."
            if unmeasured
            else "every criterion was measured; the remaining uncertainty is sample size — "
            "the validation universe is a few dozen securities, not a survey."
        ),
        "",
        "**Monthly cost:** "
        + (
            cost.reason if cost is not None else "no declared cost input was supplied for this run."
        ),
    ]
    return lines


def render_report(
    metadata: RunMetadata,
    cells: Sequence[CellRecord],
    scores: Sequence[ProviderScore],
    *,
    generated_at: datetime,
    declared: Sequence[DeclaredScore] = (),
    tiers: Mapping[str, str] | None = None,
    git_commit: str | None = None,
    declared_verified_on: date | None = None,
    provisional: bool = False,
    provisional_reason: str = "",
    max_failure_examples: int = MAX_FAILURE_EXAMPLES,
) -> str:
    """Render the whole Results section, heading and generated markers included.

    ``generated_at`` is an input, not ``now()``: pass something derived from the run (the CLI
    passes its start time) and regeneration is byte-identical. Set ``provisional`` for any
    render from fake or test data.
    """
    lines = [RESULTS_HEADING, ""]
    lines += _banner(provisional, provisional_reason)
    lines += [""]
    lines += _provenance(
        metadata,
        cells,
        scores,
        generated_at=generated_at,
        git_commit=git_commit,
        tiers=tiers or {},
        declared_verified_on=declared_verified_on,
    )
    lines += [""]
    if not scores:
        lines += ["### Summary", "", "No provider scores were supplied for this run.", ""]
    else:
        lines += _summary(scores, cells)
        lines += [""]
        for score in _ranked(scores):
            lines += _provider_section(score, cells, max_failure_examples)
            lines += [""]
    lines += _recommendation(scores, declared)
    lines += ["", GENERATED_END]
    return "\n".join(lines).rstrip() + "\n"


def update_results_section(doc_path: Path, rendered: str) -> None:
    """Replace the generated region of ``doc_path`` with ``rendered``.

    Everything before the ``## Results`` heading is preserved byte for byte. So is everything
    after :data:`GENERATED_END`, if the document already carries the markers — a hand-written
    section below the generated region survives regeneration. On a document that has no end
    marker yet (the first generation), the Results heading and everything after it is
    replaced.
    """
    text = doc_path.read_text()
    heading = text.find(RESULTS_HEADING)
    if heading == -1:
        raise ReportError(
            f"{doc_path} has no {RESULTS_HEADING!r} heading: the generator writes only inside "
            "that section and will not invent it"
        )
    end = text.find(GENERATED_END)
    tail = text[end + len(GENERATED_END) :] if end != -1 else "\n"
    if tail.startswith("\n"):
        tail = tail[1:]
    doc_path.write_text(text[:heading] + rendered + tail)


def _git_commit(repo: Path) -> str | None:
    try:
        result = subprocess.run(
            ["git", "-C", str(repo), "rev-parse", "HEAD"],  # fixed argv, no shell
            capture_output=True,
            text=True,
            check=True,
            timeout=10,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    return result.stdout.strip() or None


def main(argv: list[str] | None = None) -> int:
    """``uv run python -m trp.bakeoff.report --run-dir … --doc docs/…``."""
    parser = argparse.ArgumentParser(prog="trp.bakeoff.report", description=__doc__)
    parser.add_argument("--run-dir", required=True, type=Path, help="a persisted run directory")
    parser.add_argument("--doc", type=Path, help="document to update; omit to print to stdout")
    parser.add_argument(
        "--provisional",
        action="store_true",
        help="stamp the section as generated from fake/test data",
    )
    parser.add_argument("--provisional-reason", default="")
    parser.add_argument(
        "--tier",
        action="append",
        default=[],
        metavar="PROVIDER=TIER",
        help="the subscription tier tested, recorded in the provenance block",
    )
    args = parser.parse_args(argv)

    metadata, cells = load_run(args.run_dir)
    tiers = dict(pair.split("=", 1) for pair in args.tier if "=" in pair)
    scores = [score_provider(name, cells) for name in sorted(metadata.providers)]
    rendered = render_report(
        metadata,
        cells,
        scores,
        generated_at=metadata.started_at,  # a property of the run: regeneration is idempotent
        tiers=tiers,
        git_commit=_git_commit(Path.cwd()),
        provisional=args.provisional,
        provisional_reason=args.provisional_reason,
    )
    if args.doc is None:
        print(rendered)
        return 0
    update_results_section(args.doc, rendered)
    print(f"updated {args.doc} Results section from run {metadata.run_id}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
