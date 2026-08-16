"""Data-quality checks over canonical prices. **Warnings, not fixes.**

No check in this module mutates, drops, rewrites or repairs a single row. A check that
quietly forward-fills a gap or clips an outlier destroys the evidence that something is
wrong with the source, and leaves a dataset that looks clean while being less trustworthy
than the dirty one (CLAUDE.md; docs/QUANT_PRINCIPLES.md). Every finding therefore carries
enough evidence — dates, observed values, the threshold applied — for a human to
adjudicate, and adjudication decisions belong in exclusion lists recorded with the
experiment, never here.

The checks, each a pure function from frames to findings so it can be tested in isolation:

``non_positive_price``
    Zero, negative or null prices, and null or negative volume — bars that reached storage
    despite the QNT-013 invariants (a provider file loaded around the domain model, say).
``calendar_gap``
    Trading days per the QNT-016 exchange calendar, inside the listing's validity window,
    with no bar. A holiday is not a gap; a day after delisting is not a gap.
``extreme_move``
    A close-to-close move of at least ``extreme_move`` with no corporate action within
    ``corporate_action_window_days`` of the date. This is the split-inversion detector
    QNT-015's risk section asks for: an unexplained move whose price ratio sits close to a
    simple event ratio (1/2, 1/3, 1/10, …) is reported at ERROR as a *possible unrecorded
    corporate action*, because an unrecorded split inverts the sign of every factor-model
    signal computed over that window. An identical move with the split actually recorded
    produces nothing.
``stale_price_run``
    ``stale_run_days`` or more consecutive bars at an identical close, with the run's
    volumes as evidence — a repeated close with volume is a quiet stock, a repeated close
    with zero volume is usually a provider carrying the last print forward.
``zero_volume`` / ``volume_outlier``
    Zero-volume trading days (reported separately, as the ticket requires) and volume
    beyond ``volume_outlier_multiple`` times a trailing median. Half days are excluded from
    the outlier check (QNT-016) because a shortened session is the known-benign explanation
    for anomalous volume; zero-volume days are still reported on half days, flagged as such
    in their evidence so they can be dismissed at a glance.
``adjustment_warning``
    Warnings raised by the adjustment engine, principally rights issues, which DEC-009
    deliberately leaves unadjusted. Those securities have knowingly wrong adjusted series
    before the issue date, and this report is where that becomes visible.

Every threshold is configuration (:class:`ValidationThresholds`) with a documented default,
recorded in the report so a finding can always be read against the rule that produced it.

Point-in-time: ``validate_prices`` requires ``as_of`` and only uses corporate actions with
``available_at <= as_of``. A check reproducing a historical state must not explain a move
with an action the vendor had not yet published.

Arithmetic: exact throughout. The extreme-move test is expressed as
``close >= prev x (1 + t)`` / ``close <= prev x (1 - t)`` — multiplication and comparison
only, which Polars evaluates on Decimals exactly — and division happens in ``Fraction``,
on the handful of flagged rows only. No float64 anywhere (DEC-005).
"""

import json
from collections.abc import Iterable, Mapping, Sequence
from datetime import UTC, date, datetime
from decimal import Decimal
from enum import StrEnum
from fractions import Fraction

import polars as pl

from trp.canonical.calendars import (
    CalendarError,
    TradingCalendar,
    UnknownExchange,
    get_trading_calendar,
)
from trp.canonical.prices import PRICE_DECIMAL, bars_to_frame
from trp.derived.adjustments import AdjustmentComputation
from trp.domain.corporate_actions import CorporateAction
from trp.domain.prices import DailyBar
from trp.domain.security import FrozenModel, Listing


class Severity(StrEnum):
    """INFO is context, WARNING wants a look, ERROR says the data is probably wrong."""

    INFO = "info"
    WARNING = "warning"
    ERROR = "error"


CHECK_NAMES: tuple[str, ...] = (
    "non_positive_price",
    "calendar_gap",
    "extreme_move",
    "stale_price_run",
    "zero_volume",
    "volume_outlier",
    "adjustment_warning",
    # Diagnostics: the checks reporting on their own ability to run.
    "listing_unknown",
    "calendar_unavailable",
    "calendar_range_clamped",
)


class ValidationThresholds(FrozenModel):
    """Every tunable, with its default. Recorded in the report that used it.

    Defaults are chosen to produce a *short list worth reading* rather than a complete one:
    the extreme-move check in particular has a real false-positive rate (a takeover
    approach or a profit warning is a genuine 30% move), so its default is set high enough
    that what it returns is mostly worth adjudicating. They are starting points to be
    retuned against real ingested data, not constants of nature.
    """

    extreme_move: Decimal = Decimal("0.5")
    """Absolute close-to-close move that counts as extreme; 0.5 = 50%. The bound is
    **inclusive** — a move of exactly this size fires. That matters: an unrecorded 2-for-1
    split lands on exactly -50%, and a strict comparison would let the single most common
    case this check exists to find fall one step outside it."""

    corporate_action_window_days: int = 3
    """Calendar days either side of a move in which an action is taken to explain it."""

    explaining_action_types: tuple[str, ...] = ("split", "rights_issue", "merger", "delisting")
    """Action types that suppress an extreme-move finding. Dividends are deliberately
    absent: an ordinary dividend cannot cause a 50% move, so treating one as an
    explanation would suppress exactly the findings worth having. A dividend near the date
    is attached to the finding as evidence instead."""

    unrecorded_event_tolerance: Decimal = Decimal("0.02")
    """Relative distance within which a price ratio counts as matching a simple event
    ratio, and so as a *possible unrecorded corporate action*."""

    stale_run_days: int = 5
    """Consecutive bars at an identical close before a run is reported. Must exceed 2 —
    a close repeated once is unremarkable."""

    zero_volume_run_days: int = 1
    """Consecutive zero-volume trading days before a run is reported."""

    volume_outlier_multiple: int = 20
    """Multiple of the trailing median volume above which a day is an outlier."""

    volume_median_window: int = 21
    """Trailing bars (excluding the day itself) the median is taken over — a month."""

    volume_median_min_samples: int = 10
    """Trailing bars required before the outlier check will fire at all."""


DEFAULT_THRESHOLDS = ValidationThresholds()

# Price ratios (new close / previous close) produced by common events, with what each
# would mean. A 2-for-1 split takes the price to one half; a 1-for-10 consolidation takes
# it to ten times. The decimal-shift entries overlap the 10:1 events deliberately — the
# finding names both readings and lets a human choose.
_CANDIDATE_EVENT_RATIOS: tuple[tuple[Fraction, str], ...] = (
    (Fraction(1, 2), "an unrecorded 2-for-1 split"),
    (Fraction(1, 3), "an unrecorded 3-for-1 split"),
    (Fraction(1, 4), "an unrecorded 4-for-1 split"),
    (Fraction(1, 5), "an unrecorded 5-for-1 split"),
    (Fraction(2, 3), "an unrecorded 3-for-2 split"),
    (Fraction(2, 5), "an unrecorded 5-for-2 split"),
    (Fraction(1, 10), "an unrecorded 10-for-1 split, or a price quoted a decimal place low"),
    (Fraction(1, 100), "a price quoted two decimal places low, or a pence/pound unit error"),
    (Fraction(3, 2), "an unrecorded 2-for-3 consolidation"),
    (Fraction(2), "an unrecorded 1-for-2 consolidation"),
    (Fraction(3), "an unrecorded 1-for-3 consolidation"),
    (Fraction(5), "an unrecorded 1-for-5 consolidation"),
    (Fraction(10), "an unrecorded 1-for-10 consolidation, or a price quoted a decimal place high"),
    (Fraction(100), "a price quoted two decimal places high, or a pound/pence unit error"),
)

_SEQUENCE_KEY = ("security_id", "source")
_SORT_KEY = ("security_id", "source", "trade_date")

_MAX_LISTED_DATES = 20

_ONE_DAY = date(2000, 1, 2) - date(2000, 1, 1)


class Finding(FrozenModel):
    """One thing worth a human's attention, with the evidence to adjudicate it."""

    check: str
    severity: Severity
    security_id: str | None
    start_date: date | None
    end_date: date | None
    detail: str
    threshold: str | None = None
    evidence: tuple[tuple[str, str], ...] = ()

    @property
    def evidence_map(self) -> dict[str, str]:
        return dict(self.evidence)


def _finding(
    check: str,
    severity: Severity,
    *,
    security_id: str | None = None,
    start_date: date | None = None,
    end_date: date | None = None,
    detail: str,
    threshold: str | None = None,
    evidence: Mapping[str, object] | None = None,
) -> Finding:
    return Finding(
        check=check,
        severity=severity,
        security_id=security_id,
        start_date=start_date,
        end_date=end_date if end_date is not None else start_date,
        detail=detail,
        threshold=threshold,
        evidence=tuple((key, str(value)) for key, value in (evidence or {}).items()),
    )


class ValidationReport(FrozenModel):
    """The output of a run: findings as data, plus what was checked and under which rules.

    ``counts_by_check`` carries an entry for every check, zero included, so that a run
    over clean data is distinguishable from a run in which a check silently did not
    execute — and so that a jump in one check's count after an ingestion is itself a
    signal.
    """

    generated_at: datetime
    as_of: datetime
    thresholds: ValidationThresholds
    securities_checked: int
    bars_checked: int
    first_trade_date: date | None
    last_trade_date: date | None
    findings: tuple[Finding, ...]
    counts_by_check: tuple[tuple[str, int], ...]

    @property
    def counts(self) -> dict[str, int]:
        return dict(self.counts_by_check)

    def by_check(self, check: str) -> tuple[Finding, ...]:
        return tuple(f for f in self.findings if f.check == check)

    def by_severity(self, severity: Severity) -> tuple[Finding, ...]:
        return tuple(f for f in self.findings if f.severity is severity)

    def to_frame(self) -> pl.DataFrame:
        """Findings as a flat frame. Evidence is JSON so the schema stays fixed."""
        schema: dict[str, pl.DataType | type[pl.DataType]] = {
            "check": pl.Utf8,
            "severity": pl.Utf8,
            "security_id": pl.Utf8,
            "start_date": pl.Date,
            "end_date": pl.Date,
            "detail": pl.Utf8,
            "threshold": pl.Utf8,
            "evidence": pl.Utf8,
        }
        rows = [
            {
                "check": f.check,
                "severity": str(f.severity),
                "security_id": f.security_id,
                "start_date": f.start_date,
                "end_date": f.end_date,
                "detail": f.detail,
                "threshold": f.threshold,
                "evidence": json.dumps(f.evidence_map, sort_keys=True),
            }
            for f in self.findings
        ]
        return pl.DataFrame(rows, schema=schema)

    def to_markdown(self, *, limit: int = 50) -> str:
        """A terminal-readable summary: the counts first, then the findings themselves."""
        lines = [
            "# Price validation report",
            "",
            f"- as of: {self.as_of.isoformat()}",
            f"- generated: {self.generated_at.isoformat()}",
            f"- securities: {self.securities_checked}; bars: {self.bars_checked}",
            f"- date range: {self.first_trade_date} to {self.last_trade_date}",
            f"- findings: {len(self.findings)}",
            "",
            "| check | findings |",
            "| --- | --- |",
        ]
        lines.extend(f"| {check} | {count} |" for check, count in self.counts_by_check)
        if not self.findings:
            lines.extend(["", "No findings."])
            return "\n".join(lines)

        lines.extend(
            [
                "",
                "| severity | check | security | dates | detail | evidence |",
                "| --- | --- | --- | --- | --- | --- |",
            ]
        )
        for finding in self.findings[:limit]:
            dates = (
                f"{finding.start_date}"
                if finding.start_date == finding.end_date
                else f"{finding.start_date}..{finding.end_date}"
            )
            evidence = "; ".join(f"{k}={v}" for k, v in finding.evidence)
            lines.append(
                f"| {finding.severity} | {finding.check} | {finding.security_id or '-'} "
                f"| {dates} | {finding.detail} | {evidence} |"
            )
        if len(self.findings) > limit:
            lines.append("")
            lines.append(f"_{len(self.findings) - limit} further findings omitted._")
        return "\n".join(lines)


def _sorted(prices: pl.DataFrame) -> pl.DataFrame:
    """A sorted copy. Every check works on its own copy; the caller's frame is untouched."""
    return prices.sort(list(_SORT_KEY))


def _dates(dates: Sequence[date]) -> str:
    if len(dates) <= _MAX_LISTED_DATES:
        return ", ".join(d.isoformat() for d in dates)
    shown = ", ".join(d.isoformat() for d in dates[:_MAX_LISTED_DATES])
    return f"{shown}, … (+{len(dates) - _MAX_LISTED_DATES} more)"


def check_non_positive_prices(prices: pl.DataFrame) -> tuple[Finding, ...]:
    """Prices at or below zero, null prices, and null or negative volume."""
    price_columns = ("open", "high", "low", "close")
    bad = _sorted(prices).filter(
        pl.any_horizontal(
            *[pl.col(c).is_null() | (pl.col(c) <= Decimal(0)) for c in price_columns],
            pl.col("volume").is_null(),
            pl.col("volume") < 0,
        )
    )
    findings: list[Finding] = []
    for row in bad.iter_rows(named=True):
        offending = {
            column: row[column]
            for column in (*price_columns, "volume")
            if row[column] is None or row[column] <= 0
        }
        findings.append(
            _finding(
                "non_positive_price",
                Severity.ERROR,
                security_id=row["security_id"],
                start_date=row["trade_date"],
                detail=(
                    "bar has a non-positive or missing value; it violates the DailyBar "
                    "invariants and cannot have been written through the domain model"
                ),
                threshold="> 0",
                evidence={"source": row["source"], **offending},
            )
        )
    return tuple(findings)


def _mics_by_security(listings: Iterable[Listing]) -> dict[str, list[Listing]]:
    by_security: dict[str, list[Listing]] = {}
    for listing in listings:
        by_security.setdefault(listing.security_id, []).append(listing)
    return by_security


def _clamped_window(calendar: TradingCalendar, start: date, end: date) -> tuple[date, date] | None:
    """``[start, end]`` intersected with the calendar's supported range, or None."""
    lower = max(start, calendar.first_supported_date)
    upper = min(end, calendar.last_supported_date)
    if lower > upper:
        return None
    return lower, upper


def check_calendar_gaps(
    prices: pl.DataFrame,
    listings: Sequence[Listing],
    *,
    start: date | None = None,
    end: date | None = None,
) -> tuple[Finding, ...]:
    """Trading days inside a listing's validity window with no bar, as contiguous runs.

    The window checked is the listing's validity range intersected with the overall date
    range of the data under inspection, so a security that listed late produces no gaps
    before its IPO and one that delisted produces none afterwards. A security with no
    listing is reported (``listing_unknown``) rather than skipped in silence.
    """
    frame = _sorted(prices)
    if frame.is_empty():
        return ()
    overall_start = start if start is not None else frame.get_column("trade_date").min()
    overall_end = end if end is not None else frame.get_column("trade_date").max()
    assert isinstance(overall_start, date) and isinstance(overall_end, date)

    by_security = _mics_by_security(listings)
    findings: list[Finding] = []
    for security_id in frame.get_column("security_id").unique(maintain_order=True).to_list():
        observed = set(
            frame.filter(pl.col("security_id") == security_id).get_column("trade_date").to_list()
        )
        security_listings = by_security.get(security_id, [])
        if not security_listings:
            findings.append(
                _finding(
                    "listing_unknown",
                    Severity.INFO,
                    security_id=security_id,
                    start_date=overall_start,
                    end_date=overall_end,
                    detail=(
                        "no listing supplied, so no exchange calendar applies and calendar "
                        "gaps cannot be checked for this security"
                    ),
                )
            )
            continue
        for listing in security_listings:
            findings.extend(_gaps_for_listing(listing, observed, overall_start, overall_end))
    return tuple(findings)


def _gaps_for_listing(
    listing: Listing, observed: set[date], overall_start: date, overall_end: date
) -> list[Finding]:
    window_start = max(listing.valid_from, overall_start)
    # valid_to is exclusive: the last day the listing was live is the day before.
    window_end = (
        min(listing.valid_to - _ONE_DAY, overall_end)
        if listing.valid_to is not None
        else overall_end
    )
    if window_start > window_end:
        return []
    try:
        calendar = get_trading_calendar(listing.mic)
    except UnknownExchange as unknown:
        return [
            _finding(
                "calendar_unavailable",
                Severity.WARNING,
                security_id=listing.security_id,
                start_date=window_start,
                end_date=window_end,
                detail=f"no trading calendar for MIC {listing.mic}: {unknown}",
            )
        ]

    findings: list[Finding] = []
    clamped = _clamped_window(calendar, window_start, window_end)
    if clamped is None:
        return [
            _finding(
                "calendar_range_clamped",
                Severity.INFO,
                security_id=listing.security_id,
                start_date=window_start,
                end_date=window_end,
                detail=(
                    f"the whole window lies outside the supported range of the "
                    f"{listing.mic} calendar; no gap check was performed"
                ),
            )
        ]
    if clamped != (window_start, window_end):
        findings.append(
            _finding(
                "calendar_range_clamped",
                Severity.INFO,
                security_id=listing.security_id,
                start_date=window_start,
                end_date=window_end,
                detail=(
                    f"window narrowed to {clamped[0]}..{clamped[1]}: the {listing.mic} "
                    "calendar does not cover the whole of it, and weekday logic is not a "
                    "substitute"
                ),
            )
        )
    try:
        missing = calendar.missing_sessions(observed, clamped[0], clamped[1])
    except CalendarError as error:  # pragma: no cover — clamping should prevent this
        return [
            _finding(
                "calendar_unavailable",
                Severity.WARNING,
                security_id=listing.security_id,
                start_date=clamped[0],
                end_date=clamped[1],
                detail=f"calendar query failed: {error}",
            )
        ]
    sessions = calendar.sessions_between(clamped[0], clamped[1])
    for run in _contiguous_session_runs(missing, sessions):
        findings.append(
            _finding(
                "calendar_gap",
                Severity.WARNING,
                security_id=listing.security_id,
                start_date=run[0],
                end_date=run[-1],
                detail=(
                    f"{len(run)} trading day(s) on {listing.mic} with no bar while the "
                    "listing was live"
                ),
                threshold="every trading day in the listing window has a bar",
                evidence={
                    "mic": listing.mic,
                    "missing_days": len(run),
                    "dates": _dates(run),
                },
            )
        )
    return findings


def _contiguous_session_runs(missing: Sequence[date], sessions: Sequence[date]) -> list[list[date]]:
    """Group missing dates into runs contiguous *in trading days*, not calendar days."""
    position = {session: index for index, session in enumerate(sessions)}
    runs: list[list[date]] = []
    for missing_date in missing:
        index = position[missing_date]
        if runs and position[runs[-1][-1]] == index - 1:
            runs[-1].append(missing_date)
        else:
            runs.append([missing_date])
    return runs


def _actions_by_security(
    actions: Sequence[CorporateAction], *, as_of: datetime
) -> dict[str, list[CorporateAction]]:
    known: dict[str, list[CorporateAction]] = {}
    for action in actions:
        if action.available_at > as_of:
            continue  # not yet published as at the reproduction date
        known.setdefault(action.security_id, []).append(action)
    return known


def _matching_event_ratio(ratio: Fraction, tolerance: Decimal) -> str | None:
    relative = Fraction(tolerance)
    for candidate, description in _CANDIDATE_EVENT_RATIOS:
        if abs(ratio - candidate) <= relative * candidate:
            return description
    return None


def check_extreme_moves(
    prices: pl.DataFrame,
    actions: Sequence[CorporateAction] = (),
    *,
    as_of: datetime,
    thresholds: ValidationThresholds = DEFAULT_THRESHOLDS,
) -> tuple[Finding, ...]:
    """Bar-over-bar raw-close moves at or beyond the threshold with no action to match.

    Bounds are computed by multiplication so the comparison is exact on Decimals; the move
    itself is then derived in ``Fraction`` for the flagged rows only. Sequences are taken
    per (security, source): two providers' series must not be interleaved into a fake move.
    """
    frame = _sorted(prices)
    if frame.is_empty():
        return ()
    threshold = thresholds.extreme_move
    upper = pl.lit(Decimal(1) + threshold, dtype=PRICE_DECIMAL)
    lower = pl.lit(Decimal(1) - threshold, dtype=PRICE_DECIMAL)
    moves = frame.with_columns(
        previous_close=pl.col("close").shift(1).over(list(_SEQUENCE_KEY)),
        previous_date=pl.col("trade_date").shift(1).over(list(_SEQUENCE_KEY)),
    ).filter(
        pl.col("previous_close").is_not_null()
        & (pl.col("previous_close") > Decimal(0))
        & (
            (pl.col("close") >= pl.col("previous_close") * upper)
            | (pl.col("close") <= pl.col("previous_close") * lower)
        )
    )

    known = _actions_by_security(actions, as_of=as_of)
    window = thresholds.corporate_action_window_days
    findings: list[Finding] = []
    for row in moves.iter_rows(named=True):
        ratio = Fraction(row["close"]) / Fraction(row["previous_close"])
        move = ratio - 1
        nearby = [
            action
            for action in known.get(row["security_id"], [])
            if abs((action.ex_date - row["trade_date"]).days) <= window
        ]
        explaining = [
            action for action in nearby if action.action_type in thresholds.explaining_action_types
        ]
        if explaining:
            continue  # a recorded event accounts for it; nothing to adjudicate
        resembles = _matching_event_ratio(ratio, thresholds.unrecorded_event_tolerance)
        evidence: dict[str, object] = {
            "source": row["source"],
            "previous_date": row["previous_date"],
            "previous_close": row["previous_close"],
            "close": row["close"],
            "move": _as_decimal(move),
            "price_ratio": f"{ratio.numerator}/{ratio.denominator}",
            "currency": row["currency"],
            "actions_within_window": (
                "; ".join(f"{a.action_type}@{a.ex_date}" for a in nearby) if nearby else "none"
            ),
        }
        if resembles is None:
            detail = (
                "close-to-close move beyond the threshold with no corporate action "
                "recorded near the date — genuine event, or missing action data"
            )
            severity = Severity.WARNING
        else:
            detail = f"move is consistent with {resembles}, but no such action is recorded"
            severity = Severity.ERROR
            evidence["resembles"] = resembles
        findings.append(
            _finding(
                "extreme_move",
                severity,
                security_id=row["security_id"],
                start_date=row["previous_date"],
                end_date=row["trade_date"],
                detail=detail,
                threshold=f"|move| >= {threshold}",
                evidence=evidence,
            )
        )
    return tuple(findings)


def _as_decimal(value: Fraction) -> Decimal:
    return (Decimal(value.numerator) / Decimal(value.denominator)).quantize(Decimal("0.000001"))


def _runs(frame: pl.DataFrame, changed: pl.Expr) -> pl.DataFrame:
    """Label maximal runs over the sorted frame: a new run starts where ``changed`` is true."""
    group_changed = pl.any_horizontal(
        *[pl.col(column) != pl.col(column).shift(1) for column in _SEQUENCE_KEY]
    )
    return frame.with_columns(
        _run=(group_changed | changed).fill_null(True).cum_sum(),
    )


def check_stale_prices(
    prices: pl.DataFrame, *, thresholds: ValidationThresholds = DEFAULT_THRESHOLDS
) -> tuple[Finding, ...]:
    """Runs of identical closes at or beyond ``stale_run_days``, with their volumes."""
    frame = _sorted(prices)
    if frame.is_empty():
        return ()
    runs = (
        _runs(frame, pl.col("close") != pl.col("close").shift(1))
        .group_by("_run")
        .agg(
            pl.col("security_id").first(),
            pl.col("source").first(),
            pl.col("close").first(),
            pl.col("trade_date").first().alias("start_date"),
            pl.col("trade_date").last().alias("end_date"),
            pl.col("volume").alias("volumes"),
            pl.len().alias("length"),
        )
        .filter(pl.col("length") >= thresholds.stale_run_days)
        .sort(["security_id", "source", "start_date"])
    )
    findings: list[Finding] = []
    for row in runs.iter_rows(named=True):
        volumes = list(row["volumes"])
        all_zero = all(volume == 0 for volume in volumes)
        findings.append(
            _finding(
                "stale_price_run",
                Severity.ERROR if all_zero else Severity.WARNING,
                security_id=row["security_id"],
                start_date=row["start_date"],
                end_date=row["end_date"],
                detail=(
                    f"close unchanged at {row['close']} for {row['length']} consecutive bars"
                    + (
                        " with no volume on any of them — the provider is most likely "
                        "carrying the last print forward"
                        if all_zero
                        else ""
                    )
                ),
                threshold=f"run length >= {thresholds.stale_run_days}",
                evidence={
                    "source": row["source"],
                    "close": row["close"],
                    "run_length": row["length"],
                    "volumes": ", ".join(str(volume) for volume in volumes),
                    "total_volume": sum(volumes),
                },
            )
        )
    return tuple(findings)


def _half_days_by_security(
    prices: pl.DataFrame, listings: Sequence[Listing]
) -> dict[str, frozenset[date]]:
    if prices.is_empty():
        return {}
    start = prices.get_column("trade_date").min()
    end = prices.get_column("trade_date").max()
    assert isinstance(start, date) and isinstance(end, date)
    by_security: dict[str, set[date]] = {}
    for listing in listings:
        try:
            calendar = get_trading_calendar(listing.mic)
        except UnknownExchange:
            continue
        clamped = _clamped_window(calendar, start, end)
        if clamped is None:
            continue
        half_days = {
            session
            for session in calendar.sessions_between(*clamped)
            if calendar.is_half_day(session)
        }
        by_security.setdefault(listing.security_id, set()).update(half_days)
    return {security: frozenset(days) for security, days in by_security.items()}


def check_zero_volume(
    prices: pl.DataFrame,
    listings: Sequence[Listing] = (),
    *,
    thresholds: ValidationThresholds = DEFAULT_THRESHOLDS,
) -> tuple[Finding, ...]:
    """Runs of zero-volume days. Half days are reported too, but flagged as such."""
    frame = _sorted(prices)
    if frame.is_empty():
        return ()
    half_days = _half_days_by_security(frame, listings)
    runs = (
        _runs(frame, (pl.col("volume") == 0) != (pl.col("volume").shift(1) == 0))
        .filter(pl.col("volume") == 0)
        .group_by("_run")
        .agg(
            pl.col("security_id").first(),
            pl.col("source").first(),
            pl.col("trade_date").alias("dates"),
            pl.col("trade_date").first().alias("start_date"),
            pl.col("trade_date").last().alias("end_date"),
            pl.len().alias("length"),
        )
        .filter(pl.col("length") >= thresholds.zero_volume_run_days)
        .sort(["security_id", "source", "start_date"])
    )
    findings: list[Finding] = []
    for row in runs.iter_rows(named=True):
        dates = list(row["dates"])
        security_half_days = half_days.get(row["security_id"], frozenset())
        on_half_days = [d for d in dates if d in security_half_days]
        findings.append(
            _finding(
                "zero_volume",
                Severity.WARNING,
                security_id=row["security_id"],
                start_date=row["start_date"],
                end_date=row["end_date"],
                detail=(
                    f"{row['length']} trading day(s) with zero volume — a suspended line, "
                    "a provider gap, or a genuinely untraded day"
                ),
                threshold=f"run length >= {thresholds.zero_volume_run_days}",
                evidence={
                    "source": row["source"],
                    "zero_volume_days": row["length"],
                    "dates": _dates(dates),
                    "half_days_in_run": _dates(on_half_days) if on_half_days else "none",
                },
            )
        )
    return tuple(findings)


def check_volume_outliers(
    prices: pl.DataFrame,
    listings: Sequence[Listing] = (),
    *,
    thresholds: ValidationThresholds = DEFAULT_THRESHOLDS,
) -> tuple[Finding, ...]:
    """Volume beyond a multiple of the trailing median, half days excluded (QNT-016).

    The trailing median is floored to whole shares before comparison, keeping the decision
    in exact integer arithmetic; flooring makes the test marginally more sensitive, which
    is the safe direction for a warning-only check.
    """
    frame = _sorted(prices)
    if frame.is_empty():
        return ()
    half_days = _half_days_by_security(frame, listings)
    window = thresholds.volume_median_window
    flagged = (
        frame.with_columns(
            trailing_median=pl.col("volume")
            .shift(1)
            .rolling_median(window_size=window, min_samples=thresholds.volume_median_min_samples)
            .over(list(_SEQUENCE_KEY))
            .floor()
            .cast(pl.Int64),
        )
        .filter(
            pl.col("trailing_median").is_not_null()
            & (pl.col("trailing_median") > 0)
            & (pl.col("volume") > pl.col("trailing_median") * thresholds.volume_outlier_multiple)
        )
        .sort(list(_SORT_KEY))
    )
    findings: list[Finding] = []
    for row in flagged.iter_rows(named=True):
        if row["trade_date"] in half_days.get(row["security_id"], frozenset()):
            continue  # a shortened session explains anomalous volume; QNT-016
        findings.append(
            _finding(
                "volume_outlier",
                Severity.WARNING,
                security_id=row["security_id"],
                start_date=row["trade_date"],
                detail=(
                    f"volume {row['volume']} is more than "
                    f"{thresholds.volume_outlier_multiple}x the trailing median "
                    f"{row['trailing_median']}"
                ),
                threshold=(
                    f"volume > {thresholds.volume_outlier_multiple} x median of the "
                    f"previous {window} bars"
                ),
                evidence={
                    "source": row["source"],
                    "volume": row["volume"],
                    "trailing_median_volume": row["trailing_median"],
                    "window_bars": window,
                },
            )
        )
    return tuple(findings)


def check_adjustment_warnings(computation: AdjustmentComputation) -> tuple[Finding, ...]:
    """Surface the adjustment engine's own warnings — DEC-009 rights issues above all.

    A rights issue is deliberately not adjusted for, so the adjusted series before its
    ex-date is knowingly wrong. That is a data-quality fact about the security and belongs
    in this report, not only in a provenance blob nobody reads.
    """
    findings: list[Finding] = []
    for message in computation.provenance.warnings:
        security_id, warning_date = _parse_adjustment_warning(message)
        findings.append(
            _finding(
                "adjustment_warning",
                Severity.WARNING,
                security_id=security_id,
                start_date=warning_date,
                detail=message,
                threshold="adjustment engine provenance warnings are always reported",
                evidence={
                    "as_of": computation.provenance.as_of.isoformat(),
                    "actions_applied": computation.provenance.action_count_applied,
                },
            )
        )
    return tuple(findings)


def _parse_adjustment_warning(message: str) -> tuple[str | None, date | None]:
    """Recover the security and date the engine named, best effort.

    The warnings are prose by design (they are meant to be read), so this parse is a
    convenience for grouping the report — the full message is always kept as the detail,
    and a parse failure costs nothing.
    """
    security_id: str | None = None
    warning_date: date | None = None
    if message.startswith("security ") and ":" in message:
        candidate = message[len("security ") : message.index(":")].strip()
        security_id = candidate or None
    for word in message.replace(",", " ").split():
        try:
            warning_date = date.fromisoformat(word)
        except ValueError:
            continue
        break
    return security_id, warning_date


def validate_prices(
    prices: pl.DataFrame,
    *,
    as_of: datetime,
    actions: Sequence[CorporateAction] = (),
    listings: Sequence[Listing] = (),
    adjustment: AdjustmentComputation | None = None,
    thresholds: ValidationThresholds = DEFAULT_THRESHOLDS,
    start: date | None = None,
    end: date | None = None,
) -> ValidationReport:
    """Run every check and collect the findings. Nothing is modified, ever.

    ``prices`` is a frame in ``PRICES_DAILY_SCHEMA`` (what ``price_store.read_prices``
    returns). ``as_of`` bounds the corporate actions available to explain a move.
    """
    if as_of.tzinfo is None:
        raise ValueError("as_of must be timezone-aware (UTC)")

    findings: list[Finding] = [
        *check_non_positive_prices(prices),
        *check_calendar_gaps(prices, listings, start=start, end=end),
        *check_extreme_moves(prices, actions, as_of=as_of, thresholds=thresholds),
        *check_stale_prices(prices, thresholds=thresholds),
        *check_zero_volume(prices, listings, thresholds=thresholds),
        *check_volume_outliers(prices, listings, thresholds=thresholds),
    ]
    if adjustment is not None:
        findings.extend(check_adjustment_warnings(adjustment))

    counts = dict.fromkeys(CHECK_NAMES, 0)
    for finding in findings:
        counts[finding.check] = counts.get(finding.check, 0) + 1

    first = prices.get_column("trade_date").min() if not prices.is_empty() else None
    last = prices.get_column("trade_date").max() if not prices.is_empty() else None
    assert first is None or isinstance(first, date)
    assert last is None or isinstance(last, date)
    return ValidationReport(
        generated_at=datetime.now(UTC),
        as_of=as_of,
        thresholds=thresholds,
        securities_checked=int(prices.get_column("security_id").n_unique()),
        bars_checked=int(prices.height),
        first_trade_date=first,
        last_trade_date=last,
        findings=tuple(findings),
        counts_by_check=tuple(counts.items()),
    )


def validate_bars(
    bars: Sequence[DailyBar],
    *,
    as_of: datetime,
    actions: Sequence[CorporateAction] = (),
    listings: Sequence[Listing] = (),
    adjustment: AdjustmentComputation | None = None,
    thresholds: ValidationThresholds = DEFAULT_THRESHOLDS,
    start: date | None = None,
    end: date | None = None,
) -> ValidationReport:
    """:func:`validate_prices` over domain models rather than a stored frame."""
    return validate_prices(
        bars_to_frame(list(bars)),
        as_of=as_of,
        actions=actions,
        listings=listings,
        adjustment=adjustment,
        thresholds=thresholds,
        start=start,
        end=end,
    )
