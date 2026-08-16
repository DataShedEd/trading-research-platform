"""QNT-035 — point-in-time fundamental and revision checks.

What a vendor calls "historical fundamentals since 2000" is almost always the *current view*
of history: restated figures with no publication timestamps, presented as though they had
always been known. These checks establish, per provider and per market, whether that is what
is on offer.

==========================================  ==================  ============================
check                                       criterion           what it decides
==========================================  ==================  ============================
``fundamental_timestamp_presence``          pit_fundamentals    are publication timestamps
                                                                present, and on what share
                                                                of records
``fundamental_timestamp_plausibility``      pit_fundamentals    or are they placeholders
                                                                (period end repeated, epoch,
                                                                one uniform lag, all 1st of
                                                                the month)
``fundamental_availability_class``          pit_fundamentals    can a defensible
                                                                ``available_at`` be derived
                                                                (QNT-020), and from what
``restatement_visibility``                  revision_history    is the original figure
                                                                retrievable at all
``filing_lag_distribution``                 pit_fundamentals    measurement: observed lag
                                                                percentiles versus DEC-007
==========================================  ==================  ============================

Three timestamps get conflated constantly and are kept apart here: ``period_end`` (a
market-local date), a *filing* or *accepted* date (when a document reached a regulator or the
vendor), and true *first-known* availability (when the information became public). Providers
routinely label the second as though it were the third, so every finding records the field
name inspected verbatim.

**The filing-lag check is a measurement, not a judgement.** It emits one finding carrying the
observed distribution with :data:`~trp.bakeoff.payloads.MEASUREMENT_PREFIX` and outcome
``not_applicable``, which scoring ignores by construction: how conservative *our* DEC-007
imputation is says nothing about whether the *provider* passed anything. The report renders
these findings in their own section. Where the observed 90th percentile exceeds the assumed
lag, the explanation says so plainly — that is a superseding-decision trigger for DEC-007,
not a provider failure.
"""

from collections.abc import Sequence
from datetime import UTC, date, datetime, time, timedelta
from decimal import Decimal
from enum import StrEnum
from math import ceil

from trp.bakeoff.checks import Check, Criterion, Finding, Outcome, register, registered_checks
from trp.bakeoff.checks_corporate_actions import finding_for, relative_difference
from trp.bakeoff.payloads import (
    DECISION_TRIGGER,
    MEASUREMENT_PREFIX,
    ParsedPages,
    StatementRow,
    parse_statements,
)
from trp.bakeoff.universe.loader import (
    AwkwardProperty,
    Market,
    RestatementFact,
    UniverseEntry,
)
from trp.providers.base import Dataset

TIMESTAMP_PRESENCE_THRESHOLD = Decimal("0.9")
"""A provider whose timestamps cover less than 90% of statements cannot support point-in-time
research on the rest, which must then be imputed and flagged (DEC-007)."""

PLACEHOLDER_UNIFORMITY_THRESHOLD = Decimal("0.9")
"""If nine records in ten share one identical lag, that is a default, not a filing date."""

MIN_PLACEHOLDER_SAMPLE = 3
"""Below three records, "every lag is identical" is a coincidence, not a pattern."""

EPOCH_CUTOFF = date(1980, 1, 1)
"""Timestamps before this are epoch/placeholder artefacts, not filings."""

RESTATEMENT_RELATIVE_TOLERANCE = Decimal("0.01")
"""Restatement expectations are announced figures ("approximately GBP 250m"), so an exact
match is the wrong test; 1% distinguishes the original from the restated value everywhere in
the validation universe."""

MIN_LAG_SAMPLE = 3
"""Percentiles below this sample size are reported with the count and nothing else claimed."""

DEC007_ASSUMED_LAG_DAYS: dict[Market, dict[str, int]] = {
    Market.UK: {"annual": 90, "interim": 60, "quarterly": 60},
    Market.US: {"annual": 60, "interim": 45, "quarterly": 45},
    Market.EU: {"annual": 90, "interim": 60, "quarterly": 60},
}
"""The per-market reporting lags this check measures DEC-007 against.

DEC-007 records the *rule* — impute ``available_at`` as period end plus a documented
per-market lag — but no lag table exists in the codebase yet (ingestion has none as of
QNT-035, and ``trp.domain.fundamentals`` only names ``uk-annual-lag-90d`` as an example of
the rule's spelling). These values are therefore this check's explicit, reviewable
assumption, matching that example. When ingestion grows a real table, import it here instead
of maintaining two.
"""

_PERIOD_ALIASES: dict[str, str] = {
    "annual": "annual",
    "fy": "annual",
    "year": "annual",
    "yearly": "annual",
    "a": "annual",
    "interim": "interim",
    "half": "interim",
    "half_year": "interim",
    "h1": "interim",
    "semi_annual": "interim",
    "quarterly": "quarterly",
    "quarter": "quarterly",
    "q": "quarterly",
    "q1": "quarterly",
    "q2": "quarterly",
    "q3": "quarterly",
    "q4": "quarterly",
}


def period_class(row: StatementRow) -> str:
    """The period type in the three terms DEC-007 reasons about; ``annual`` when unstated.

    Unknown period types fall back to ``annual`` because it carries the longest assumed lag:
    an unclassifiable record should be imputed late, never early.
    """
    if row.period_type is None:
        return "annual"
    return _PERIOD_ALIASES.get(row.period_type.strip().lower().replace("-", "_"), "annual")


class AvailabilityClass(StrEnum):
    """What a provider makes it possible to know, best first.

    The order is the point: it is the classification the rubric's highest-weighted
    fundamental criterion turns on, so it is declared once, here, and compared by rank.
    """

    FIRST_KNOWN = "first_known"  # a genuine first-publication timestamp
    FILING_ONLY = "filing_only"  # filing/accepted dates; available_at derivable, coarse
    PERIOD_END_ONLY = "period_end_only"  # nothing but period ends: DEC-007 imputation required
    NOTHING_USABLE = "nothing_usable"  # not even period ends

    @property
    def rank(self) -> int:
        return _CLASS_ORDER.index(self)

    @property
    def acceptable(self) -> bool:
        """Whether a defensible ``available_at`` can be derived from provider data alone.

        ``FILING_ONLY`` passes: a filing date is coarse but real, and QNT-020 can carry it.
        ``PERIOD_END_ONLY`` fails: everything after it is our imputation, not the provider's
        evidence, and scoring it as a pass would credit the provider for our conservatism.
        """
        return self in (AvailabilityClass.FIRST_KNOWN, AvailabilityClass.FILING_ONLY)


_CLASS_ORDER: tuple[AvailabilityClass, ...] = (
    AvailabilityClass.FIRST_KNOWN,
    AvailabilityClass.FILING_ONLY,
    AvailabilityClass.PERIOD_END_ONLY,
    AvailabilityClass.NOTHING_USABLE,
)


def _today() -> date:
    return datetime.now(UTC).date()


def timestamp_is_usable(row: StatementRow, *, today: date) -> bool:
    """A publication timestamp we would be willing to derive ``available_at`` from.

    Strictly after the period end (a filing cannot precede the period it reports), not in
    the future, and not an epoch-style placeholder.
    """
    stamp = row.publication_at()
    if stamp is None or row.period_end is None:
        return False
    if stamp.date() <= row.period_end:
        return False
    return not (stamp.date() > today or stamp.date() < EPOCH_CUTOFF)


def lag_days(row: StatementRow) -> int | None:
    stamp = row.publication_at()
    if stamp is None or row.period_end is None:
        return None
    return (stamp.date() - row.period_end).days


def percentile(values: Sequence[int], fraction: Decimal) -> int:
    """Nearest-rank percentile — no interpolation, so the value reported is one observed."""
    ordered = sorted(values)
    index = max(1, ceil(float(fraction) * len(ordered))) - 1
    return ordered[index]


def derive_available_at(
    row: StatementRow, market: Market
) -> tuple[datetime | None, bool, str | None]:
    """The ``available_at`` this check layer would derive, and whether it is imputed.

    Returns ``(available_at, imputed, imputation_rule)``. A usable publication timestamp is
    used as-is; otherwise DEC-007 applies (period end plus the assumed per-market lag) and
    the rule is named so QNT-020 records can carry it. ``(None, ...)`` when the statement
    has no period end either — nothing defensible can be derived and nothing is invented.
    """
    if timestamp_is_usable(row, today=_today()):
        stamp = row.publication_at()
        assert stamp is not None
        return stamp, False, None
    if row.period_end is None:
        return None, True, None
    kind = period_class(row)
    days = DEC007_ASSUMED_LAG_DAYS[market][kind]
    imputed = datetime.combine(row.period_end, time.min, tzinfo=UTC) + timedelta(days=days)
    return imputed, True, f"{market.value}-{kind}-lag-{days}d"


def _no_statements(parsed: ParsedPages[StatementRow], expected: str) -> Finding:
    return Finding(
        outcome=Outcome.FAIL,
        expected=expected,
        observed=parsed.failure_evidence() if parsed.errors else f"{parsed.pages} page(s), 0 rows",
        explanation=(
            "no fundamental statements could be read from the payload: with nothing to inspect, "
            "point-in-time availability cannot be established at all"
        ),
    )


class FundamentalTimestampPresenceCheck(Check):
    """What share of statements carry a usable publication timestamp, and from which field.

    Runs over financial-period metadata as well as fundamentals: for some providers the
    announcement date lives there and nowhere else, and a criterion scored only over the
    statements endpoint would understate them.
    """

    name = "fundamental_timestamp_presence"
    criterion = Criterion.PIT_FUNDAMENTALS
    datasets = frozenset({Dataset.FUNDAMENTALS, Dataset.FINANCIAL_PERIODS})
    properties = None

    def __init__(self, today: date | None = None) -> None:
        self._today = today

    def run(self, entry: UniverseEntry, payloads: Sequence[bytes]) -> list[Finding]:
        today = self._today or _today()
        parsed = parse_statements(payloads)
        expected = (
            f">= {TIMESTAMP_PRESENCE_THRESHOLD:.0%} of statements carry a usable publication "
            "timestamp (after period end, not future, not a placeholder)"
        )
        if not parsed.items:
            return [_no_statements(parsed, expected)]
        usable = [r for r in parsed.items if timestamp_is_usable(r, today=today)]
        fraction = Decimal(len(usable)) / Decimal(len(parsed.items))
        fields = sorted({f for r in usable if (f := r.publication_field()) is not None})
        field_note = ", ".join(fields) or "none"
        observed = (
            f"{len(usable)}/{len(parsed.items)} ({fraction:.0%}) via field(s) {field_note} "
            f"[{entry.market.value}]"
        )
        if fraction >= TIMESTAMP_PRESENCE_THRESHOLD:
            return [
                Finding(
                    outcome=Outcome.PASS,
                    expected=expected,
                    observed=observed,
                    explanation=(
                        f"publication timestamps are present for {entry.entity_name} on the "
                        f"{entry.market.value} market; field names recorded verbatim above, "
                        "since a vendor's label is not evidence of what the value means"
                    ),
                )
            ]
        return [
            Finding(
                outcome=Outcome.FAIL,
                expected=expected,
                observed=observed,
                explanation=(
                    "too few statements carry a usable publication timestamp: availability for "
                    "the remainder must be imputed conservatively (DEC-007) and flagged, which "
                    "bounds what any factor built on them can claim"
                ),
            )
        ]


class FundamentalTimestampPlausibilityCheck(Check):
    """Are the timestamps real, or a default wearing a filing date's clothes?

    A filing date exactly equal to ``period_end`` for every record is not a filing date. So
    is a lag identical to the day across every record, a cluster on the first of the month,
    or an epoch value. Each pattern is reported as its own failure reason: they have
    different causes, and treating any of them as a real timestamp leaks months of future
    information while looking fully point-in-time.
    """

    name = "fundamental_timestamp_plausibility"
    criterion = Criterion.PIT_FUNDAMENTALS
    datasets = frozenset({Dataset.FUNDAMENTALS})
    properties = None

    def __init__(self, today: date | None = None) -> None:
        self._today = today

    def run(self, entry: UniverseEntry, payloads: Sequence[bytes]) -> list[Finding]:
        today = self._today or _today()
        parsed = parse_statements(payloads)
        stamped = [r for r in parsed.items if r.publication_at() is not None]
        expected = "publication timestamps that vary like real filings"
        if not parsed.items:
            return [_no_statements(parsed, expected)]
        if not stamped:
            return [
                Finding(
                    outcome=Outcome.NOT_APPLICABLE,
                    expected=expected,
                    observed=f"0/{len(parsed.items)} statements carry any timestamp",
                    explanation=(
                        "no timestamps to assess for plausibility; absence is scored by "
                        "fundamental_timestamp_presence, not counted twice here"
                    ),
                )
            ]

        equal_to_period_end = [
            r
            for r in stamped
            if r.period_end is not None
            and (stamp := r.publication_at()) is not None
            and stamp.date() == r.period_end
        ]
        if len(equal_to_period_end) == len(stamped):
            return [
                Finding(
                    outcome=Outcome.FAIL,
                    expected=expected,
                    observed=f"all {len(stamped)} timestamps equal their period end",
                    explanation=(
                        "the 'filing date' is the period end repeated: a default, not a filing "
                        "date. Consumed as an availability timestamp it leaks the whole "
                        "reporting lag — weeks to months of future information — while the "
                        "dataset appears fully point-in-time"
                    ),
                )
            ]

        implausible = [
            r
            for r in stamped
            if (stamp := r.publication_at()) is not None
            and (stamp.date() < EPOCH_CUTOFF or stamp.date() > today)
        ]
        if implausible:
            sample = sorted(
                str(stamp.date()) for r in implausible if (stamp := r.publication_at()) is not None
            )[:5]
            return [
                Finding(
                    outcome=Outcome.FAIL,
                    expected=expected,
                    observed=f"{len(implausible)}/{len(stamped)} out of range, e.g. {sample}",
                    explanation=(
                        f"timestamps before {EPOCH_CUTOFF} or after today are placeholders "
                        "(epoch defaults, far-future sentinels), not publication dates"
                    ),
                )
            ]

        lags = [lag for r in stamped if (lag := lag_days(r)) is not None]
        if len(lags) >= MIN_PLACEHOLDER_SAMPLE:
            modal = max(set(lags), key=lags.count)
            share = Decimal(lags.count(modal)) / Decimal(len(lags))
            if share >= PLACEHOLDER_UNIFORMITY_THRESHOLD:
                return [
                    Finding(
                        outcome=Outcome.FAIL,
                        expected=expected,
                        observed=f"{share:.0%} of {len(lags)} records share a lag of {modal} days",
                        explanation=(
                            "suspicious uniformity: real filings do not arrive the same number "
                            "of days after every period end. This is an imputation the vendor "
                            "has already made and is presenting as observed data"
                        ),
                    )
                ]

        first_of_month = [
            r for r in stamped if (stamp := r.publication_at()) is not None and stamp.day == 1
        ]
        if (
            len(stamped) >= MIN_PLACEHOLDER_SAMPLE
            and Decimal(len(first_of_month)) / Decimal(len(stamped))
            >= PLACEHOLDER_UNIFORMITY_THRESHOLD
        ):
            return [
                Finding(
                    outcome=Outcome.FAIL,
                    expected=expected,
                    observed=f"{len(first_of_month)}/{len(stamped)} timestamps fall on the 1st",
                    explanation=(
                        "timestamps clustering on the first of the month are a month-precision "
                        "value padded to a date, not a filing timestamp"
                    ),
                )
            ]

        distinct_lags = len(set(lags))
        return [
            Finding(
                outcome=Outcome.PASS,
                expected=expected,
                observed=f"{len(stamped)} timestamps, {distinct_lags} distinct lag(s)",
                explanation=(
                    "timestamps vary as real filings do: no period-end repetition, no epoch or "
                    "future values, no single dominant lag, no first-of-month clustering"
                ),
            )
        ]


class FundamentalAvailabilityClassCheck(Check):
    """Classify the provider into the ordered set the rubric's heaviest criterion turns on.

    ``first_known`` > ``filing_only`` > ``period_end_only`` > ``nothing_usable``. The first
    two pass — an ``available_at`` can be derived from provider evidence, coarsely in the
    second case. The last two fail: what would fill the gap is our own DEC-007 imputation,
    and crediting the provider for our conservatism is exactly the self-deception this epic
    exists to prevent.
    """

    name = "fundamental_availability_class"
    criterion = Criterion.PIT_FUNDAMENTALS
    datasets = frozenset({Dataset.FUNDAMENTALS})
    properties = None

    def __init__(self, today: date | None = None) -> None:
        self._today = today

    def classify(self, rows: Sequence[StatementRow], *, today: date) -> AvailabilityClass:
        if not rows:
            return AvailabilityClass.NOTHING_USABLE
        first_known = [
            r for r in rows if r.first_known_at is not None and timestamp_is_usable(r, today=today)
        ]
        if first_known:
            return AvailabilityClass.FIRST_KNOWN
        usable = [r for r in rows if timestamp_is_usable(r, today=today)]
        if Decimal(len(usable)) / Decimal(len(rows)) >= TIMESTAMP_PRESENCE_THRESHOLD:
            return AvailabilityClass.FILING_ONLY
        if any(r.period_end is not None for r in rows):
            return AvailabilityClass.PERIOD_END_ONLY
        return AvailabilityClass.NOTHING_USABLE

    def run(self, entry: UniverseEntry, payloads: Sequence[bytes]) -> list[Finding]:
        today = self._today or _today()
        parsed = parse_statements(payloads)
        expected = (
            f"availability class {AvailabilityClass.FIRST_KNOWN.value} or "
            f"{AvailabilityClass.FILING_ONLY.value} (a defensible available_at per QNT-020)"
        )
        if not parsed.items:
            return [_no_statements(parsed, expected)]
        classification = self.classify(parsed.items, today=today)
        fields = sorted(
            {str(r.publication_field()) for r in parsed.items if r.publication_field() is not None}
        )
        observed = (
            f"{classification.value} [{entry.market.value}] from field(s) "
            f"{', '.join(fields) or 'none'} over {len(parsed.items)} statement(s)"
        )
        explanations = {
            AvailabilityClass.FIRST_KNOWN: (
                "the provider exposes a genuine first-known timestamp: available_at is the "
                "provider's evidence rather than our assumption"
            ),
            AvailabilityClass.FILING_ONLY: (
                "filing/accepted dates only — usable but coarse: what is recorded is when the "
                "document reached a regulator or the vendor, not when the market could act on "
                "it. QNT-020 must carry the field name, not relabel it as first-known"
            ),
            AvailabilityClass.PERIOD_END_ONLY: (
                "period ends only: every available_at would be a DEC-007 imputation, flagged "
                "as such, and point-in-time claims on this data are bounded by that assumption"
            ),
            AvailabilityClass.NOTHING_USABLE: (
                "nothing usable: not even a reliable period end, so no defensible availability "
                "can be derived at all"
            ),
        }
        return [
            Finding(
                outcome=Outcome.PASS if classification.acceptable else Outcome.FAIL,
                expected=expected,
                observed=observed,
                explanation=explanations[classification],
            )
        ]


class RestatementVisibilityCheck(Check):
    """Is the original, pre-restatement figure retrievable, or only today's view?

    Runs against the validation universe's restatement case. Reports which of the two known
    values the payload contains, whether revisions appear as distinct records with their own
    timestamps, and — the failure that matters — whether querying today silently returns only
    the restated value, which makes a backtest smarter than the investor it simulates.
    """

    name = "restatement_visibility"
    criterion = Criterion.REVISION_HISTORY
    datasets = frozenset({Dataset.FUNDAMENTALS})
    properties = frozenset({AwkwardProperty.RESTATEMENT})

    def run(self, entry: UniverseEntry, payloads: Sequence[bytes]) -> list[Finding]:
        facts = [f for f in entry.facts if isinstance(f, RestatementFact)]
        if not facts:
            return [
                Finding(
                    outcome=Outcome.NOT_APPLICABLE,
                    explanation=f"{entry.key} carries no expected restatement to check against",
                )
            ]
        parsed = parse_statements(payloads)
        return [self._one(fact, parsed) for fact in sorted(facts, key=lambda f: f.period_end)]

    def _one(self, fact: RestatementFact, parsed: ParsedPages[StatementRow]) -> Finding:
        expected = (
            f"both {fact.original_value} (original, available {fact.original_available}) and "
            f"{fact.restated_value} (restated, available {fact.restatement_available}) "
            f"{fact.unit} for {fact.line_item} @ {fact.period_end}"
        )
        candidates = [
            r for r in parsed.items if r.period_end == fact.period_end and fact.line_item in r.items
        ]
        if not candidates:
            observed = (
                parsed.failure_evidence()
                if not parsed.items
                else (
                    f"{len(parsed.items)} statement(s), none carrying {fact.line_item!r} for "
                    f"{fact.period_end}"
                )
            )
            return finding_for(
                fact,
                Outcome.FAIL,
                expected=expected,
                observed=observed,
                explanation=(
                    "the restated line item is not exposed for the affected period at all, so "
                    "revision visibility cannot even be assessed for this provider"
                ),
            )

        values = [(index, row, row.items[fact.line_item]) for index, row in enumerate(candidates)]
        originals = [
            (index, row)
            for index, row, value in values
            if relative_difference(value, fact.original_value) <= RESTATEMENT_RELATIVE_TOLERANCE
        ]
        restated = [
            (index, row)
            for index, row, value in values
            if relative_difference(value, fact.restated_value) <= RESTATEMENT_RELATIVE_TOLERANCE
        ]
        observed = f"{len(candidates)} record(s): " + ", ".join(
            f"{value} (revision={row.revision}, {row.publication_field() or 'no timestamp'}="
            f"{stamp.date() if (stamp := row.publication_at()) else 'none'})"
            for _, row, value in values
        )

        if originals and restated:
            indices = {i for i, _ in originals} | {i for i, _ in restated}
            stamps = {row.publication_at() for _, row in originals + restated}
            if len(indices) < 2 or len(stamps) < 2 or None in stamps:
                return finding_for(
                    fact,
                    Outcome.FAIL,
                    expected=expected,
                    observed=observed,
                    explanation=(
                        "original and restated figures are separate records but do not carry "
                        "distinct publication timestamps, so an as-of query cannot tell which "
                        "was knowable when — the revision is visible but not point-in-time"
                    ),
                )
            return finding_for(
                fact,
                Outcome.PASS,
                expected=expected,
                observed=observed,
                explanation=(
                    "both the original and the restated figure are retrievable as distinct "
                    "records with their own timestamps: revision history is genuinely "
                    "point-in-time for this case"
                ),
            )
        if restated:
            return finding_for(
                fact,
                Outcome.FAIL,
                expected=expected,
                observed=observed,
                explanation=(
                    "only the restated figure is retrievable: the provider serves the current "
                    "view of history and the original has been silently overwritten. Research "
                    "on this data knows the correction before it was announced"
                ),
            )
        if originals:
            return finding_for(
                fact,
                Outcome.FAIL,
                expected=expected,
                observed=observed,
                explanation=(
                    "only the original figure is present: the restatement never reached the "
                    "provider, so current-view analysis is wrong in the other direction"
                ),
            )
        return finding_for(
            fact,
            Outcome.FAIL,
            expected=expected,
            observed=observed,
            explanation=(
                "neither the original nor the restated value is present for the affected "
                "period; the provider reports a third figure this expectation cannot explain"
            ),
        )


class FilingLagDistributionCheck(Check):
    """Measure (publication timestamp minus ``period_end``) and compare it with DEC-007.

    Emits one **measurement** finding: outcome ``not_applicable`` (excluded from scoring by
    construction, see the module docstring) with the distribution in its evidence. Reports
    percentiles rather than means, because imputation must be conservative against the tail:
    a lag at roughly the 90th percentile is defensible, one at the median is not. Sample
    sizes accompany every percentile — a validation universe of a dozen securities gives a
    thin distribution, and a per-market percentile from three records is not grounds to
    change a decision.
    """

    name = "filing_lag_distribution"
    criterion = Criterion.PIT_FUNDAMENTALS
    datasets = frozenset({Dataset.FUNDAMENTALS})
    properties = None

    def __init__(self, today: date | None = None) -> None:
        self._today = today

    def run(self, entry: UniverseEntry, payloads: Sequence[bytes]) -> list[Finding]:
        today = self._today or _today()
        parsed = parse_statements(payloads)
        usable = [r for r in parsed.items if timestamp_is_usable(r, today=today)]
        assumed = DEC007_ASSUMED_LAG_DAYS[entry.market]
        expected = f"DEC-007 assumed lags for {entry.market.value}: " + ", ".join(
            f"{kind} {days}d" for kind, days in sorted(assumed.items())
        )
        if not usable:
            return [
                Finding(
                    outcome=Outcome.NOT_APPLICABLE,
                    expected=expected,
                    observed=f"0 of {len(parsed.items)} statement(s) carry a usable timestamp",
                    explanation=(
                        f"{MEASUREMENT_PREFIX}filing lag is not measurable for {entry.key} "
                        f"({entry.market.value}): no usable publication timestamps. DEC-007's "
                        "assumed lag stands untested against this provider"
                    ),
                )
            ]

        by_kind: dict[str, list[int]] = {}
        for row in usable:
            lag = lag_days(row)
            if lag is not None:
                by_kind.setdefault(period_class(row), []).append(lag)

        summaries: list[str] = []
        verdicts: list[str] = []
        for kind in sorted(by_kind):
            lags = by_kind[kind]
            p50 = percentile(lags, Decimal("0.5"))
            p75 = percentile(lags, Decimal("0.75"))
            p90 = percentile(lags, Decimal("0.9"))
            summaries.append(
                f"{kind}: n={len(lags)}, median={p50}d, p75={p75}d, p90={p90}d, max={max(lags)}d"
            )
            limit = assumed[kind]
            if len(lags) < MIN_LAG_SAMPLE:
                verdicts.append(
                    f"{kind}: n={len(lags)} is below the {MIN_LAG_SAMPLE}-record floor, so the "
                    f"percentiles are reported but support no conclusion about the {limit}d "
                    "assumption"
                )
            elif p90 > limit:
                verdicts.append(
                    f"{DECISION_TRIGGER}{kind}: observed p90 {p90}d EXCEEDS DEC-007's assumed "
                    f"{limit}d — the assumption is not conservative enough and imputed "
                    "availability would be earlier than reality for the tail. Supersede DEC-007 "
                    "with a new decision entry; do not edit DEC-007 in place"
                )
            else:
                verdicts.append(
                    f"{kind}: observed p90 {p90}d is within DEC-007's assumed {limit}d, so the "
                    "imputation is conservative for this sample"
                )
        return [
            Finding(
                outcome=Outcome.NOT_APPLICABLE,
                expected=expected,
                observed="; ".join(summaries),
                explanation=(
                    f"{MEASUREMENT_PREFIX}filing-lag distribution for {entry.key} "
                    f"({entry.market.value}). " + ". ".join(verdicts) + "."
                ),
            )
        ]


PIT_FUNDAMENTAL_CHECKS: tuple[Check, ...] = (
    FilingLagDistributionCheck(),
    FundamentalAvailabilityClassCheck(),
    FundamentalTimestampPlausibilityCheck(),
    FundamentalTimestampPresenceCheck(),
    RestatementVisibilityCheck(),
)


def register_all() -> None:
    """Register this module's checks. Idempotent, so tests may clear and re-register."""
    known = {check.name for check in registered_checks()}
    for check in PIT_FUNDAMENTAL_CHECKS:
        if check.name not in known:
            register(check)


register_all()
