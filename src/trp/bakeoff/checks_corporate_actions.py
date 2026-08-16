"""QNT-034 — corporate-action and price-accuracy checks.

Five narrow, single-purpose check families, each comparing one provider payload against the
validation universe's known-correct expectations:

===============================  =========================  ===============================
check                            criterion                  tolerance
===============================  =========================  ===============================
``split_ratio_and_ex_date``      corporate_action_accuracy  ratio exact, ex-date exact
``dividend_amount_and_ex_date``  corporate_action_accuracy  amount 0.5% relative, date exact
``delisted_price_history``       delisted_coverage          final row within 5 calendar days
``price_history_depth``          historical_depth           >= 20 years of daily history
``raw_vs_adjusted_consistency``  corporate_action_accuracy  0.5% relative reconstruction err
``price_continuity_ticker``      corporate_action_accuracy  <= 7-day gap, <= 25% jump
===============================  =========================  ===============================

Design notes worth knowing before reading a failure:

- **Ratios are new-per-old.** A provider using old:new is a real finding and is reported as
  an inverted ratio in its own words, never silently accepted — Citigroup's 1-for-10 in the
  universe turns a 100x error into a visible one.
- **Units are compared explicitly** (GBX versus GBP), never numerically. A factor-of-100
  discrepancy is reported as a unit failure, because reporting it as an amount discrepancy
  invites someone to "fix" it with a scale factor.
- **Expectations are not infallible.** A mismatch against a fact carrying
  ``needs_verification`` is still a ``FAIL`` (suppressing it would hide provider errors) but
  its explanation is prefixed with :data:`~trp.bakeoff.payloads.EXPECTATION_REVIEW_PREFIX`
  and says the expectation must be re-verified against a primary source before the failure
  is counted against the provider.
- **A check only ever sees its own cell's payloads**, so raw-versus-adjusted reconciliation
  reads the corporate actions the *price* payload carries (the neutral convention's optional
  ``actions`` key on a price page) and is ``not_applicable`` when the payload carries no
  actions or no adjusted series — never a pass by omission.

Payload shapes: see :mod:`trp.bakeoff.payloads` (and its honesty warning — the convention is
provisional until a real adapter lands).
"""

from collections.abc import Iterable, Sequence
from datetime import date
from decimal import Decimal

from trp.bakeoff.checks import Check, Criterion, Finding, Outcome, register, registered_checks
from trp.bakeoff.payloads import (
    EXPECTATION_REVIEW_PREFIX,
    ActionRow,
    ParsedPages,
    PriceRow,
    normalise_unit,
    parse_actions,
    parse_prices,
)
from trp.bakeoff.universe.loader import (
    AwkwardProperty,
    DelistingFact,
    DividendFact,
    FactBase,
    SplitFact,
    TickerChangeFact,
    UniverseEntry,
)
from trp.providers.base import Dataset

DIVIDEND_RELATIVE_TOLERANCE = Decimal("0.005")
"""0.5% on dividend amounts: providers round declared pence differently, but a genuinely
different dividend is never within half a percent."""

EX_DATE_WINDOW_DAYS = 5
"""How far either side of an expected ex-date to look before calling an action *missing*
rather than *misdated*. The two failures have different causes and different fixes."""

DELISTING_SHORTFALL_TOLERANCE_DAYS = 5
"""A final trading day within a working week of the delisting is coverage; a month short is
a truncated series pretending to be a complete one."""

DELISTING_OVERRUN_TOLERANCE_DAYS = 5
"""Prices materially past the delisting date are fabricated, not late — reported separately
from a shortfall because a backfilled final price is the more dangerous failure."""

DEPTH_TARGET_YEARS = 20
"""Every candidate advertises "30+ years"; 20 is the depth this platform's factor research
actually needs, so it is what the criterion asserts."""

ADJUSTED_RELATIVE_TOLERANCE = Decimal("0.005")
"""Reconstruction error above 0.5% means the adjusted series cannot be explained by the
provider's own action records."""

TICKER_CHANGE_MAX_GAP_DAYS = 7
"""A ticker change should cost at most a long weekend of trading days."""

TICKER_CHANGE_JUMP_TOLERANCE = Decimal("0.25")
"""A 25% overnight move across a rename, with no action to explain it, is a stitching error
in the provider's history rather than a market event."""

CONTINUITY_WINDOW_DAYS = 30
"""Window either side of a ticker change inspected for gaps and duplicate dates."""

_PENCE_PAIRS: dict[tuple[str, str], Decimal] = {
    ("GBX", "GBP"): Decimal("0.01"),
    ("GBP", "GBX"): Decimal(100),
}


def unit_conversion(from_unit: str, to_unit: str) -> Decimal | None:
    """Factor expressing a ``from_unit`` value in ``to_unit``; ``None`` if unrelated."""
    if from_unit == to_unit:
        return Decimal(1)
    return _PENCE_PAIRS.get((from_unit, to_unit))


def relative_difference(observed: Decimal, expected: Decimal) -> Decimal:
    if expected == 0:
        return Decimal(0) if observed == 0 else Decimal(1)
    return abs(observed - expected) / abs(expected)


def finding_for(
    fact: FactBase,
    outcome: Outcome,
    *,
    expected: str,
    observed: str,
    explanation: str,
) -> Finding:
    """A finding whose explanation carries the expectation-review flag where it belongs."""
    if outcome is Outcome.FAIL and fact.needs_verification:
        stop = "" if explanation.rstrip().endswith((".", "!", "?")) else "."
        explanation = (
            f"{EXPECTATION_REVIEW_PREFIX}{explanation}{stop} The expectation itself is flagged "
            f"needs_verification (source: {fact.source}; verified {fact.verified_on}) and must "
            "be re-verified against a primary source before this failure is counted against "
            "the provider."
        )
    return Finding(outcome=outcome, expected=expected, observed=observed, explanation=explanation)


def _not_applicable(explanation: str) -> list[Finding]:
    return [Finding(outcome=Outcome.NOT_APPLICABLE, explanation=explanation)]


def _unparseable(parsed: ParsedPages[object], what: str) -> Finding:
    return Finding(
        outcome=Outcome.FAIL,
        expected=f"a parseable {what} payload (see trp.bakeoff.payloads)",
        observed=parsed.failure_evidence(),
        explanation=(
            f"the provider's {what} payload could not be read at all, so nothing about its "
            "content can be asserted; treat as a fetch/shape failure, not as absent data"
        ),
    )


def _facts[F: FactBase](entry: UniverseEntry, kind: type[F]) -> list[F]:
    return [f for f in entry.facts if isinstance(f, kind)]


def _of_kind(actions: Iterable[ActionRow], kind: str) -> list[ActionRow]:
    return [a for a in actions if a.kind == kind and a.ex_date is not None]


class SplitRatioAndExDateCheck(Check):
    """Every expected split/consolidation is present with the right ratio on the right day.

    Ratios compare exactly: a split ratio is a small rational, and "nearly 4:1" is not a
    thing. An observed ratio equal to the reciprocal of the expectation is called out as a
    convention inversion rather than as a numeric error, because the fix differs.
    """

    name = "split_ratio_and_ex_date"
    criterion = Criterion.CORPORATE_ACTION_ACCURACY
    datasets = frozenset({Dataset.CORPORATE_ACTIONS})
    properties = frozenset({AwkwardProperty.SPLIT, AwkwardProperty.CONSOLIDATION})

    def run(self, entry: UniverseEntry, payloads: Sequence[bytes]) -> list[Finding]:
        facts = _facts(entry, SplitFact)
        if not facts:
            return _not_applicable(
                f"{entry.key} carries no expected split/consolidation to check against"
            )
        parsed = parse_actions(payloads)
        if not parsed.items and parsed.errors:
            return [_unparseable(parsed, "corporate-action")]
        splits = _of_kind(parsed.items, "split")
        return [self._one(fact, splits) for fact in sorted(facts, key=lambda f: f.ex_date)]

    def _one(self, fact: SplitFact, splits: Sequence[ActionRow]) -> Finding:
        expected_ratio = Decimal(fact.new_shares) / Decimal(fact.old_shares)
        expected = f"{fact.new_shares}:{fact.old_shares} (={expected_ratio}) ex {fact.ex_date}"
        exact = [a for a in splits if a.ex_date == fact.ex_date]
        if not exact:
            near = [
                a
                for a in splits
                if a.ex_date is not None
                and abs((a.ex_date - fact.ex_date).days) <= EX_DATE_WINDOW_DAYS
            ]
            if near:
                observed = ", ".join(f"{a.ex_date} ratio {a.ratio()}" for a in near)
                return finding_for(
                    fact,
                    Outcome.FAIL,
                    expected=expected,
                    observed=observed,
                    explanation=(
                        "a split is present but on the wrong ex-date: prices adjust on the "
                        "wrong day, so returns are wrong on both days"
                    ),
                )
            listed = ", ".join(str(a.ex_date) for a in splits) or "no split records at all"
            return finding_for(
                fact,
                Outcome.FAIL,
                expected=expected,
                observed=listed,
                explanation=(
                    "the split is missing entirely: an unadjusted ratio change appears in the "
                    "price series as a one-day return of the ratio itself"
                ),
            )
        action = exact[0]
        observed_ratio = action.ratio()
        if observed_ratio is None:
            return finding_for(
                fact,
                Outcome.FAIL,
                expected=expected,
                observed=action.label,
                explanation=(
                    "the split is present on the right date but carries no usable ratio, so the "
                    "adjustment factor cannot be derived from the provider's own record"
                ),
            )
        if observed_ratio == expected_ratio:
            return finding_for(
                fact,
                Outcome.PASS,
                expected=expected,
                observed=f"{observed_ratio} ex {action.ex_date}",
                explanation="ratio and ex-date match the verified expectation exactly",
            )
        if observed_ratio != 0 and Decimal(1) / observed_ratio == expected_ratio:
            return finding_for(
                fact,
                Outcome.FAIL,
                expected=expected,
                observed=f"{observed_ratio} ex {action.ex_date}",
                explanation=(
                    "the ratio is inverted: the provider states old:new where this platform "
                    "reads new:old. Applied unchanged it produces an error of the square of "
                    "the ratio, and it is a convention difference, not a data error"
                ),
            )
        return finding_for(
            fact,
            Outcome.FAIL,
            expected=expected,
            observed=f"{observed_ratio} ex {action.ex_date}",
            explanation="the split ratio disagrees with the verified expectation",
        )


class DividendAmountAndExDateCheck(Check):
    """Expected dividends are present with the right amount, unit and ex-date.

    Applies to every entry (``properties = None``): a dividend expectation can attach to any
    security, and gating on the ``special_dividend`` property would silently skip ordinary
    dividend facts recorded elsewhere in the universe. Entries with no ``DividendFact`` are
    ``not_applicable``.
    """

    name = "dividend_amount_and_ex_date"
    criterion = Criterion.CORPORATE_ACTION_ACCURACY
    datasets = frozenset({Dataset.CORPORATE_ACTIONS})
    properties = None

    def run(self, entry: UniverseEntry, payloads: Sequence[bytes]) -> list[Finding]:
        facts = _facts(entry, DividendFact)
        if not facts:
            return _not_applicable(f"{entry.key} carries no expected dividend to check against")
        parsed = parse_actions(payloads)
        if not parsed.items and parsed.errors:
            return [_unparseable(parsed, "corporate-action")]
        dividends = _of_kind(parsed.items, "dividend")
        return [self._one(fact, dividends) for fact in sorted(facts, key=lambda f: f.ex_date)]

    def _plausibly_the_same_dividend(self, action: ActionRow, fact: DividendFact) -> bool:
        """Is a nearby record the expected dividend misdated, or a different distribution?

        A quarterly ordinary a day either side of a special is not the special on the wrong
        date, and reporting it as one would send a reader looking for a date bug that does
        not exist. Size decides, under either reading of the unit.
        """
        if action.amount is None:
            return False
        readings = [action.amount, action.amount * Decimal(100), action.amount / Decimal(100)]
        return any(
            relative_difference(value, fact.amount) <= DIVIDEND_RELATIVE_TOLERANCE
            for value in readings
        )

    def _one(self, fact: DividendFact, dividends: Sequence[ActionRow]) -> Finding:
        kind = "special" if fact.special else "ordinary"
        expected = f"{kind} {fact.amount} {fact.unit} ex {fact.ex_date}"
        exact = [a for a in dividends if a.ex_date == fact.ex_date]
        if not exact:
            near = [
                a
                for a in dividends
                if a.ex_date is not None
                and abs((a.ex_date - fact.ex_date).days) <= EX_DATE_WINDOW_DAYS
                and self._plausibly_the_same_dividend(a, fact)
            ]
            if near:
                return finding_for(
                    fact,
                    Outcome.FAIL,
                    expected=expected,
                    observed=", ".join(f"{a.amount} {a.currency} ex {a.ex_date}" for a in near),
                    explanation=(
                        "a dividend of about the right size is present but on the wrong "
                        "ex-date, which misdates the total-return step"
                    ),
                )
            observed = f"{len(dividends)} dividend record(s), none on the expected ex-date"
            explanation = (
                "the special dividend is absent: total return is understated by the whole "
                "distribution, and the price fall on the ex-date reads as a loss"
                if fact.special
                else "the expected dividend is absent, understating total return"
            )
            return finding_for(
                fact, Outcome.FAIL, expected=expected, observed=observed, explanation=explanation
            )

        action = exact[0]
        observed_amount = action.amount
        observed_unit = normalise_unit(action.currency)
        observed = f"{observed_amount} {action.currency or '(no unit stated)'} ex {action.ex_date}"
        if observed_amount is None:
            return finding_for(
                fact,
                Outcome.FAIL,
                expected=expected,
                observed=action.label,
                explanation="a dividend record exists on the right date but carries no amount",
            )

        if observed_unit is None:
            return self._unitless(fact, action, observed_amount, expected, observed)

        conversion = unit_conversion(observed_unit, fact.unit)
        if conversion is None:
            return finding_for(
                fact,
                Outcome.FAIL,
                expected=expected,
                observed=observed,
                explanation=(
                    f"unit mismatch: the provider quotes {observed_unit}, the expectation is "
                    f"{fact.unit}, and the two are not the same money. Reported as a unit "
                    "failure rather than an amount discrepancy so nobody 'fixes' it with a "
                    "scale factor"
                ),
            )
        converted = observed_amount * conversion
        difference = relative_difference(converted, fact.amount)
        if difference <= DIVIDEND_RELATIVE_TOLERANCE:
            note = (
                ""
                if conversion == 1
                else f" (converted {observed_amount} {observed_unit} -> {converted} {fact.unit})"
            )
            return finding_for(
                fact,
                Outcome.PASS,
                expected=expected,
                observed=observed,
                explanation=(
                    f"amount within {DIVIDEND_RELATIVE_TOLERANCE} relative tolerance and ex-date "
                    f"exact{note}"
                ),
            )
        if (
            conversion != 1
            and relative_difference(observed_amount, fact.amount) <= DIVIDEND_RELATIVE_TOLERANCE
        ):
            return finding_for(
                fact,
                Outcome.FAIL,
                expected=expected,
                observed=observed,
                explanation=(
                    f"unit mismatch: the amount matches the expectation as a {fact.unit} figure "
                    f"but the payload labels it {observed_unit}. The label is wrong, not the "
                    "number — reported as a unit failure so it is not 'corrected' by a factor "
                    "of 100 in the other direction"
                ),
            )
        return finding_for(
            fact,
            Outcome.FAIL,
            expected=expected,
            observed=observed,
            explanation=(
                f"dividend amount differs by {difference:.4f} relative, outside the "
                f"{DIVIDEND_RELATIVE_TOLERANCE} tolerance, with units reconciled explicitly"
            ),
        )

    def _unitless(
        self,
        fact: DividendFact,
        action: ActionRow,
        observed_amount: Decimal,
        expected: str,
        observed: str,
    ) -> Finding:
        """No unit in the payload: a factor-of-100 gap is a unit failure, not an amount one."""
        candidates = (
            (Decimal(100), "pence quoted as pounds"),
            (Decimal("0.01"), "pounds quoted as pence"),
        )
        for factor, direction in candidates:
            if relative_difference(observed_amount * factor, fact.amount) <= (
                DIVIDEND_RELATIVE_TOLERANCE
            ):
                return finding_for(
                    fact,
                    Outcome.FAIL,
                    expected=expected,
                    observed=observed,
                    explanation=(
                        f"the payload states no unit and the amount is a factor of 100 from the "
                        f"expectation ({direction}). Reported as a unit failure: consumed as-is "
                        "it is a 100x error in every total return"
                    ),
                )
        if relative_difference(observed_amount, fact.amount) <= DIVIDEND_RELATIVE_TOLERANCE:
            return finding_for(
                fact,
                Outcome.PASS,
                expected=expected,
                observed=observed,
                explanation=(
                    f"amount matches on the expected ex-date, but the payload states no unit — "
                    f"the match assumes {fact.unit}, which an adapter must not do silently"
                ),
            )
        return finding_for(
            fact,
            Outcome.FAIL,
            expected=expected,
            observed=observed,
            explanation="dividend amount disagrees with the expectation and no unit is stated",
        )


class DelistedPriceHistoryCheck(Check):
    """A delisted security exists at all, and its prices run up to the delisting date.

    Reports the observed final trading date, its close, and the shortfall in days, so the
    report can distinguish total absence (survivorship bias) from a series that stops months
    early (a drawdown that looks survivable) from a fabricated post-delisting price.
    """

    name = "delisted_price_history"
    criterion = Criterion.DELISTED_COVERAGE
    datasets = frozenset({Dataset.PRICES})
    properties = frozenset({AwkwardProperty.FAILURE, AwkwardProperty.ACQUISITION})

    def run(self, entry: UniverseEntry, payloads: Sequence[bytes]) -> list[Finding]:
        facts = _facts(entry, DelistingFact)
        if not facts:
            return _not_applicable(f"{entry.key} has no expected delisting date to check against")
        fact = min(facts, key=lambda f: f.effective)
        parsed = parse_prices(payloads)
        expected = f"daily prices up to {fact.effective} ({fact.reason.value})"
        if not parsed.items:
            explanation = (
                "no price history at all for a delisted security: the provider's universe is "
                "survivorship-biased, which QUANT_PRINCIPLES §2 forbids relying on"
            )
            observed = parsed.failure_evidence() if parsed.errors else "0 price rows"
            return [
                finding_for(
                    fact,
                    Outcome.FAIL,
                    expected=expected,
                    observed=observed,
                    explanation=explanation,
                )
            ]

        final = max(parsed.items, key=lambda r: r.date)
        observed = f"final row {final.date} close={final.close}, {len(parsed.items)} rows"
        overrun = (final.date - fact.effective).days
        if overrun > DELISTING_OVERRUN_TOLERANCE_DAYS:
            return [
                finding_for(
                    fact,
                    Outcome.FAIL,
                    expected=expected,
                    observed=observed,
                    explanation=(
                        f"prices continue {overrun} days past the delisting date: the security "
                        "did not trade then, so these rows are fabricated or belong to a reused "
                        "ticker — worse than missing data because they look real"
                    ),
                )
            ]
        shortfall = (fact.effective - final.date).days
        if shortfall > DELISTING_SHORTFALL_TOLERANCE_DAYS:
            return [
                finding_for(
                    fact,
                    Outcome.FAIL,
                    expected=expected,
                    observed=observed,
                    explanation=(
                        f"the price history stops {shortfall} days short of the delisting: "
                        "partial coverage, so the terminal loss is missing from every backtest "
                        "that holds this security"
                    ),
                )
            ]
        return [
            finding_for(
                fact,
                Outcome.PASS,
                expected=expected,
                observed=observed,
                explanation=(
                    f"history runs to within {max(shortfall, 0)} day(s) of the delisting, inside "
                    f"the {DELISTING_SHORTFALL_TOLERANCE_DAYS}-day tolerance"
                ),
            )
        ]


class PriceHistoryDepthCheck(Check):
    """Long-lived securities have the depth the criterion claims.

    Restricted to entries tagged ``long_lived``: depth is only meaningful where the security
    genuinely existed for the period being demanded, and a delisted name's coverage is the
    delisted-coverage criterion's business, not this one.
    """

    name = "price_history_depth"
    criterion = Criterion.HISTORICAL_DEPTH
    datasets = frozenset({Dataset.PRICES})
    properties = frozenset({AwkwardProperty.LONG_LIVED})

    def run(self, entry: UniverseEntry, payloads: Sequence[bytes]) -> list[Finding]:
        parsed = parse_prices(payloads)
        expected = f">= {DEPTH_TARGET_YEARS} years of daily history for a long-lived security"
        if not parsed.items:
            return [
                Finding(
                    outcome=Outcome.FAIL,
                    expected=expected,
                    observed=parsed.failure_evidence() if parsed.errors else "0 price rows",
                    explanation=f"no price history at all for {entry.entity_name}",
                )
            ]
        earliest = min(r.date for r in parsed.items)
        latest = max(r.date for r in parsed.items)
        span_days = (latest - earliest).days
        years = Decimal(span_days) / Decimal("365.25")
        observed = f"{earliest} to {latest} ({years:.1f} years, {len(parsed.items)} rows)"
        if span_days >= DEPTH_TARGET_YEARS * 365:
            return [
                Finding(
                    outcome=Outcome.PASS,
                    expected=expected,
                    observed=observed,
                    explanation="earliest usable price date meets the depth this platform needs",
                )
            ]
        return [
            Finding(
                outcome=Outcome.FAIL,
                expected=expected,
                observed=observed,
                explanation=(
                    f"history starts at {earliest}: factor research over a full cycle is not "
                    "possible for this market at the tier tested"
                ),
            )
        ]


class RawVersusAdjustedCheck(Check):
    """The adjusted series is reconcilable with the provider's own raw prices and actions.

    Holds the provider to its own data rather than to ours: cumulative factors are built in
    ``Decimal`` from the actions the price payload carries (splits as old/new applied to
    every row before the ex-date; cash dividends as ``1 - amount / close`` on the last close
    before the ex-date), applied to raw closes, and compared with the provider's adjusted
    closes. Reports the maximum relative reconstruction error and the date it occurred.

    ``not_applicable`` — never a pass — when the payload carries no adjusted series or no
    actions to reconcile against.
    """

    name = "raw_vs_adjusted_consistency"
    criterion = Criterion.CORPORATE_ACTION_ACCURACY
    datasets = frozenset({Dataset.PRICES})
    properties = None

    def run(self, entry: UniverseEntry, payloads: Sequence[bytes]) -> list[Finding]:
        prices = parse_prices(payloads)
        if not prices.items:
            if prices.errors:
                return [_unparseable(prices, "price")]
            return _not_applicable("no price rows to reconcile")
        rows = [r for r in prices.items if r.close is not None and r.adjusted_close is not None]
        if not rows:
            return _not_applicable(
                "the price payload carries no adjusted series alongside the raw closes, so raw "
                "and adjusted cannot be compared (QUANT_PRINCIPLES §3 wants both, distinguishable)"
            )
        actions = [a for a in parse_actions(payloads).items if a.ex_date is not None]
        if not actions:
            return _not_applicable(
                "the price payload carries no corporate-action records, so its adjusted series "
                "cannot be reconciled against the provider's own actions"
            )

        identical = all(r.close == r.adjusted_close for r in rows)
        if identical:
            return [
                Finding(
                    outcome=Outcome.FAIL,
                    expected="raw and adjusted series distinguishable across known actions",
                    observed=(
                        f"adjusted == raw on all {len(rows)} rows, "
                        f"with {len(actions)} action(s) present"
                    ),
                    explanation=(
                        "the 'adjusted' close is a copy of the raw close: either the series is "
                        "unadjusted and mislabelled, or the actions were never applied. Either "
                        "way every return spanning an action is wrong"
                    ),
                )
            ]

        worst_error = Decimal(0)
        worst_row: PriceRow | None = None
        for row in rows:
            assert row.close is not None and row.adjusted_close is not None
            factor = self._cumulative_factor(row.date, actions, rows)
            error = relative_difference(row.adjusted_close, row.close * factor)
            if error > worst_error:
                worst_error, worst_row = error, row
        expected = (
            f"adjusted close reconstructable from raw close and the payload's own "
            f"{len(actions)} action(s) within {ADJUSTED_RELATIVE_TOLERANCE} relative"
        )
        if worst_row is None:
            observed = "max relative reconstruction error 0"
            return [
                Finding(
                    outcome=Outcome.PASS,
                    expected=expected,
                    observed=observed,
                    explanation="the adjusted series is fully explained by the provider's actions",
                )
            ]
        observed = (
            f"max relative error {worst_error:.6f} on {worst_row.date} "
            f"(raw {worst_row.close}, adjusted {worst_row.adjusted_close})"
        )
        if worst_error <= ADJUSTED_RELATIVE_TOLERANCE:
            return [
                Finding(
                    outcome=Outcome.PASS,
                    expected=expected,
                    observed=observed,
                    explanation="the adjusted series is explained by the provider's own actions",
                )
            ]
        return [
            Finding(
                outcome=Outcome.FAIL,
                expected=expected,
                observed=observed,
                explanation=(
                    "the adjusted series cannot be explained by the provider's own corporate "
                    "actions: at least one action is missing, wrong, or applied on a different "
                    "basis from the one it publishes"
                ),
            )
        ]

    def _cumulative_factor(
        self, on: date, actions: Sequence[ActionRow], rows: Sequence[PriceRow]
    ) -> Decimal:
        factor = Decimal(1)
        for action in actions:
            assert action.ex_date is not None
            if action.ex_date <= on:
                continue
            if action.kind == "split":
                ratio = action.ratio()
                if ratio is not None and ratio != 0:
                    factor *= Decimal(1) / ratio
            elif action.kind == "dividend" and action.amount is not None:
                reference = self._close_before(action.ex_date, rows)
                if reference is not None and reference > 0:
                    factor *= (reference - action.amount) / reference
        return factor

    def _close_before(self, ex_date: date, rows: Sequence[PriceRow]) -> Decimal | None:
        prior = [r for r in rows if r.date < ex_date and r.close is not None]
        if not prior:
            return None
        return max(prior, key=lambda r: r.date).close


class TickerChangeContinuityCheck(Check):
    """Price history spans a known ticker change without a gap, duplicate or unexplained jump.

    A rename is not a corporate event for prices: the series either continues or the provider
    has stitched two records together badly. Reports the last close before and first close
    after the change so a reader can judge which.
    """

    name = "price_continuity_across_ticker_change"
    criterion = Criterion.CORPORATE_ACTION_ACCURACY
    datasets = frozenset({Dataset.PRICES})
    properties = frozenset({AwkwardProperty.TICKER_CHANGE})

    def run(self, entry: UniverseEntry, payloads: Sequence[bytes]) -> list[Finding]:
        facts = _facts(entry, TickerChangeFact)
        if not facts:
            return _not_applicable(f"{entry.key} has no expected ticker change to check against")
        parsed = parse_prices(payloads)
        if not parsed.items:
            fact = facts[0]
            return [
                finding_for(
                    fact,
                    Outcome.FAIL,
                    expected=f"continuous prices across {fact.old_ticker} -> {fact.new_ticker}",
                    observed=parsed.failure_evidence() if parsed.errors else "0 price rows",
                    explanation="no price history at all, so continuity cannot be demonstrated",
                )
            ]
        actions = [a for a in parse_actions(payloads).items if a.ex_date is not None]
        return [
            self._one(fact, parsed.items, actions)
            for fact in sorted(facts, key=lambda f: f.effective)
        ]

    def _one(
        self, fact: TickerChangeFact, rows: Sequence[PriceRow], actions: Sequence[ActionRow]
    ) -> Finding:
        effective = fact.effective
        expected = (
            f"continuous daily prices across {fact.old_ticker} -> {fact.new_ticker} on {effective}"
        )
        before = [r for r in rows if r.date < effective]
        after = [r for r in rows if r.date >= effective]
        if not before or not after:
            side = "before" if not before else "after"
            return finding_for(
                fact,
                Outcome.FAIL,
                expected=expected,
                observed=f"{len(before)} rows before, {len(after)} rows after {effective}",
                explanation=(
                    f"the history does not span the ticker change ({side} the change there is "
                    "nothing): the provider treats one company as two, which is survivorship "
                    "bias by another name"
                ),
            )
        last = max(before, key=lambda r: r.date)
        first = min(after, key=lambda r: r.date)
        observed = f"last {last.date} close={last.close}; first {first.date} close={first.close}"

        window = [r for r in rows if abs((r.date - effective).days) <= CONTINUITY_WINDOW_DAYS]
        dates = [r.date for r in window]
        duplicates = sorted({d for d in dates if dates.count(d) > 1})
        if duplicates:
            return finding_for(
                fact,
                Outcome.FAIL,
                expected=expected,
                observed=f"duplicate dates around the change: {duplicates[:5]}",
                explanation=(
                    "the same trading day appears more than once around the ticker change: the "
                    "old and new symbol's histories have been concatenated, not joined"
                ),
            )

        gap = (first.date - last.date).days
        if gap > TICKER_CHANGE_MAX_GAP_DAYS:
            return finding_for(
                fact,
                Outcome.FAIL,
                expected=expected,
                observed=f"{gap}-day gap: {observed}",
                explanation=(
                    f"a {gap}-day hole spans the ticker change, beyond the "
                    f"{TICKER_CHANGE_MAX_GAP_DAYS}-day tolerance: returns across it are wrong "
                    "and any momentum signal reads the gap as a move"
                ),
            )

        if last.close is None or first.close is None or last.close == 0:
            return finding_for(
                fact,
                Outcome.PASS,
                expected=expected,
                observed=observed,
                explanation=(
                    f"history is continuous across the change ({gap}-day step, no duplicates); "
                    "closes are absent so the size of the step could not be assessed"
                ),
            )
        step = (first.close - last.close) / last.close
        explained = [
            a for a in actions if a.ex_date is not None and last.date < a.ex_date <= first.date
        ]
        if abs(step) > TICKER_CHANGE_JUMP_TOLERANCE and not explained:
            return finding_for(
                fact,
                Outcome.FAIL,
                expected=expected,
                observed=f"{step:.4f} step across the change: {observed}",
                explanation=(
                    "the price jumps across the ticker change with no corporate action in the "
                    "payload to explain it: the two symbols' series are on different bases "
                    "(unadjusted versus adjusted, or a different share line)"
                ),
            )
        note = (
            " (a corporate action in the payload spans the boundary and explains the step)"
            if explained
            else ""
        )
        return finding_for(
            fact,
            Outcome.PASS,
            expected=expected,
            observed=f"{step:.4f} step across the change: {observed}",
            explanation=(
                f"history is continuous across the rename: {gap}-day step, no duplicates, price "
                f"step within {TICKER_CHANGE_JUMP_TOLERANCE}{note}"
            ),
        )


CORPORATE_ACTION_CHECKS: tuple[Check, ...] = (
    DelistedPriceHistoryCheck(),
    DividendAmountAndExDateCheck(),
    PriceHistoryDepthCheck(),
    RawVersusAdjustedCheck(),
    SplitRatioAndExDateCheck(),
    TickerChangeContinuityCheck(),
)


def register_all() -> None:
    """Register this module's checks. Idempotent, so tests may clear and re-register."""
    known = {check.name for check in registered_checks()}
    for check in CORPORATE_ACTION_CHECKS:
        if check.name not in known:
            register(check)


register_all()
