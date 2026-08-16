"""The neutral payload convention the bake-off checks parse out of raw provider bytes.

Checks receive verbatim response bytes — the harness persists them before any check runs,
because part of what the bake-off measures is what a provider actually *sends*. No real
adapter exists yet (QNT-031…033 are blocked on API keys), so the QNT-034/035 checks are
written against a documented **neutral shape**: a JSON convention that every adapter will
be required to approximate, or that these parsers will be extended to accommodate — field
spelling by field spelling — once real responses exist. The shape is deliberately close to
what EODHD and FMP already return, so adapting is expected to be additive (extra accepted
key spellings in the ``_first`` lookups below) rather than a rewrite of the checks.

**This is an assumption, not a measurement.** Until a real adapter runs, a passing check
proves the check works, not that a provider does.

## The convention

Every page is one JSON object. Pages accumulate: a two-page price response is two objects
whose ``rows`` are concatenated in page order. Unknown keys are ignored, never an error.

Prices (``Dataset.PRICES``)::

    {"rows": [{"date": "2020-08-31", "close": "129.04", "adjusted_close": "127.31",
               "currency": "USD", "volume": 225702700}],
     "actions": [ ... ]}          # optional: actions carried with the price series

``actions`` on a price page is what makes raw-versus-adjusted reconciliation possible from
one cell's payloads — a check only ever sees the pages of its own dataset.

Corporate actions (``Dataset.CORPORATE_ACTIONS``)::

    {"actions": [
        {"type": "split", "ex_date": "2020-08-31", "new_shares": 4, "old_shares": 1},
        {"type": "split", "ex_date": "2011-05-09", "ratio": "1:10"},
        {"type": "dividend", "ex_date": "2004-11-15", "amount": "3.00",
         "currency": "USD", "special": true}]}

Split ratios are read as **new:old** from ``new_shares``/``old_shares``, from a ``ratio``
string (``"4:1"`` or ``"4/1"``), or from a numeric ``factor``. A provider using the
opposite convention is a finding, not a parse error — see ``checks_corporate_actions``.

Fundamentals (``Dataset.FUNDAMENTALS``, ``Dataset.FINANCIAL_PERIODS``)::

    {"statements": [
        {"period_end": "2014-08-23", "period_type": "interim",
         "filed_at": "2014-08-29", "currency": "GBP", "revision": 0,
         "items": {"trading_profit_guidance": "1100000000"}}]}

Optional per statement: ``first_known_at`` (or ``available_at``) — a genuine
first-publication timestamp, the thing QUANT_PRINCIPLES §1 actually wants; ``restated``;
``revision``. Which key supplied a timestamp is recorded verbatim on the parsed row
(``filed_at_field``) because QNT-035 must report the field it inspected, not a
normalisation of it.

## Degrading gracefully

Nothing here raises on malformed input. Each parser returns the rows it could read plus a
list of human-readable errors; checks turn "no rows and some errors" into a ``FAIL`` whose
evidence quotes the errors. A check that crashes on a provider's real bytes tells you
nothing about the provider.
"""

import json
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from datetime import UTC, date, datetime
from decimal import Decimal, InvalidOperation

NEUTRAL_CONVENTION = "neutral-1"
"""Version of the convention documented above. Bump when the accepted shape changes."""

MEASUREMENT_PREFIX = "MEASUREMENT: "
"""Prefix marking a finding that records an observation rather than judging the provider.

Measurement findings carry ``Outcome.NOT_APPLICABLE`` so scoring ignores them (a filing-lag
distribution says nothing about whether the provider passed anything), while the report
still surfaces them — see :func:`trp.bakeoff.report.render_report`.
"""

DECISION_TRIGGER = "DECISION-TRIGGER: "
"""Marks the part of a measurement that contradicts a recorded decision.

A measurement is normally just data, and the report renders it as a one-line observation.
A measurement that shows a `DECISIONS.md` assumption to be wrong — QNT-035's filing lag
exceeding DEC-007's assumed lag, say — is the reason the measurement was taken, so it is
marked and rendered in full. The marked text names the decision it contradicts.
"""

EXPECTATION_REVIEW_PREFIX = "EXPECTATION-REVIEW: "
"""Prefix marking a failure whose *expectation* is not fully verified.

The validation universe flags facts it could not confirm to the last digit
(``needs_verification``). A mismatch against one of those is still reported as ``FAIL`` —
suppressing it would hide real provider errors — but the explanation says plainly that the
expectation must be re-verified against a primary source before the failure is counted
against the provider. QNT-034's "expectation-review flag" in a two-line convention.
"""

_MAX_ERRORS_QUOTED = 3


@dataclass(frozen=True)
class ParsedPages[T]:
    """What a parser could read, plus what it could not."""

    items: tuple[T, ...] = ()
    errors: tuple[str, ...] = ()
    pages: int = 0

    def failure_evidence(self) -> str:
        """A short, quotable summary of the parse errors for a finding's ``observed``."""
        if not self.errors:
            return f"{self.pages} page(s), no usable rows"
        quoted = "; ".join(self.errors[:_MAX_ERRORS_QUOTED])
        if len(self.errors) > _MAX_ERRORS_QUOTED:
            quoted += f"; (+{len(self.errors) - _MAX_ERRORS_QUOTED} more)"
        return f"{self.pages} page(s): {quoted}"


@dataclass(frozen=True)
class PriceRow:
    date: date
    close: Decimal | None
    adjusted_close: Decimal | None
    currency: str | None
    page: int


@dataclass(frozen=True)
class ActionRow:
    kind: str  # "split", "dividend", or whatever the provider called it, lowercased
    ex_date: date | None
    new_shares: Decimal | None
    old_shares: Decimal | None
    amount: Decimal | None
    currency: str | None
    special: bool
    page: int
    label: str  # compact verbatim-ish rendering, for evidence

    def ratio(self) -> Decimal | None:
        """New-per-old, the convention this repo reads split ratios in."""
        if self.new_shares is None or self.old_shares is None or self.old_shares == 0:
            return None
        return self.new_shares / self.old_shares


@dataclass(frozen=True)
class StatementRow:
    period_end: date | None
    period_type: str | None
    filed_at: datetime | None
    filed_at_field: str | None  # the key that supplied it, verbatim
    first_known_at: datetime | None
    first_known_field: str | None
    revision: int | None
    restated: bool | None
    currency: str | None
    items: Mapping[str, Decimal] = field(default_factory=dict)
    page: int = 0

    def publication_at(self) -> datetime | None:
        """The best publication timestamp offered: first-known if any, else filed."""
        return self.first_known_at if self.first_known_at is not None else self.filed_at

    def publication_field(self) -> str | None:
        return self.first_known_field if self.first_known_at is not None else self.filed_at_field


def normalise_unit(value: str | None) -> str | None:
    """Unit codes, case-sensitively where it matters.

    ``GBp`` is the conventional spelling for pence and ``GBP`` for pounds: upper-casing
    blindly turns a pence quote into a pounds quote and produces exactly the silent
    factor-of-100 error QNT-034 exists to catch. Currency strings are therefore kept
    verbatim on parsed rows and normalised only here, at comparison time.
    """
    if value is None:
        return None
    text = value.strip()
    if text == "GBp" or text.lower() == "gbx":
        return "GBX"
    return text.upper() or None


def _first(item: Mapping[str, object], *keys: str) -> tuple[str, object] | None:
    """The first present, non-null key of ``keys`` with its name kept verbatim."""
    for key in keys:
        if key in item and item[key] is not None:
            return key, item[key]
    return None


def _decimal(value: object) -> Decimal | None:
    if isinstance(value, bool) or value is None:
        return None
    if isinstance(value, Decimal):
        return value
    if isinstance(value, int | float | str):
        try:
            return Decimal(str(value).strip())
        except (InvalidOperation, ValueError):
            return None
    return None


def _int(value: object) -> int | None:
    parsed = _decimal(value)
    if parsed is None or parsed != parsed.to_integral_value():
        return None
    return int(parsed)


def parse_date(value: object) -> date | None:
    """A date from ``YYYY-MM-DD`` or the date part of an ISO timestamp."""
    if isinstance(value, str):
        text = value.strip().replace("Z", "+00:00")
        for candidate in (text, text.split("T")[0], text.split(" ")[0]):
            try:
                return date.fromisoformat(candidate)
            except ValueError:
                continue
    return None


def parse_timestamp(value: object) -> datetime | None:
    """A timezone-aware UTC datetime (DEC-005).

    A bare date becomes midnight UTC; a naive timestamp is *assumed* UTC rather than
    rejected, because rejecting it would hide the provider's data from the checks that
    exist to describe it. Whether that assumption is safe is itself a QNT-035 finding.
    """
    if not isinstance(value, str):
        return None
    text = value.strip().replace("Z", "+00:00")
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError:
        day = parse_date(text)
        if day is None:
            return None
        return datetime.combine(day, datetime.min.time(), tzinfo=UTC)
    return parsed.astimezone(UTC) if parsed.tzinfo is not None else parsed.replace(tzinfo=UTC)


def _pages(payloads: Sequence[bytes], key: str) -> tuple[list[tuple[int, object]], list[str]]:
    """Decode each page and pull out ``key``'s list. Never raises."""
    rows: list[tuple[int, object]] = []
    errors: list[str] = []
    for index, raw in enumerate(payloads):
        if not raw.strip():
            errors.append(f"page {index}: empty")
            continue
        try:
            document = json.loads(raw)
        except (json.JSONDecodeError, UnicodeDecodeError) as exc:
            errors.append(f"page {index}: not valid JSON ({exc})")
            continue
        if not isinstance(document, dict):
            errors.append(f"page {index}: top level is {type(document).__name__}, expected object")
            continue
        block = document.get(key)
        if block is None:
            errors.append(f"page {index}: no {key!r} key (keys: {sorted(document)[:6]})")
            continue
        if not isinstance(block, list):
            errors.append(f"page {index}: {key!r} is {type(block).__name__}, expected list")
            continue
        for item in block:
            if isinstance(item, dict):
                rows.append((index, item))
            else:
                errors.append(
                    f"page {index}: {key!r} entry is {type(item).__name__}, expected object"
                )
    return rows, errors


def parse_prices(payloads: Sequence[bytes]) -> ParsedPages[PriceRow]:
    """Price rows in payload order, skipping (and reporting) rows with no usable date."""
    raw_rows, errors = _pages(payloads, "rows")
    rows: list[PriceRow] = []
    for page, item in raw_rows:
        assert isinstance(item, dict)
        found = _first(item, "date", "datetime", "d")
        day = parse_date(found[1]) if found else None
        if day is None:
            errors.append(f"page {page}: price row with no usable date ({sorted(item)[:5]})")
            continue
        close_found = _first(item, "close", "c", "close_price")
        adjusted_found = _first(item, "adjusted_close", "adjClose", "adjusted", "adj_close")
        currency_found = _first(item, "currency", "unit")
        rows.append(
            PriceRow(
                date=day,
                close=_decimal(close_found[1]) if close_found else None,
                adjusted_close=_decimal(adjusted_found[1]) if adjusted_found else None,
                currency=str(currency_found[1]).strip() if currency_found else None,
                page=page,
            )
        )
    rows.sort(key=lambda r: r.date)
    return ParsedPages(items=tuple(rows), errors=tuple(errors), pages=len(payloads))


_RATIO_SEPARATORS = (":", "/", "-for-", " for ")


def _split_shares(item: Mapping[str, object]) -> tuple[Decimal | None, Decimal | None]:
    new = _decimal(item.get("new_shares"))
    old = _decimal(item.get("old_shares"))
    if new is not None and old is not None:
        return new, old
    ratio = _first(item, "ratio", "split_ratio", "split")
    if ratio is not None and isinstance(ratio[1], str):
        text = ratio[1].strip()
        for separator in _RATIO_SEPARATORS:
            if separator in text:
                left, _, right = text.partition(separator)
                return _decimal(left), _decimal(right)
    factor = _first(item, "factor", "split_factor")
    if factor is not None:
        parsed = _decimal(factor[1])
        if parsed is not None:
            return parsed, Decimal(1)
    return new, old


def parse_actions(payloads: Sequence[bytes]) -> ParsedPages[ActionRow]:
    """Corporate actions, from a corporate-action response or a price page's ``actions``."""
    raw_rows, errors = _pages(payloads, "actions")
    actions: list[ActionRow] = []
    for page, item in raw_rows:
        assert isinstance(item, dict)
        kind_found = _first(item, "type", "action", "kind")
        kind = str(kind_found[1]).strip().lower() if kind_found else "unknown"
        ex_found = _first(item, "ex_date", "exDate", "ex_dividend_date", "date")
        amount_found = _first(item, "amount", "value", "dividend", "cash_amount")
        currency_found = _first(item, "currency", "unit")
        new, old = _split_shares(item)
        special = bool(item.get("special", False))
        actions.append(
            ActionRow(
                kind=kind,
                ex_date=parse_date(ex_found[1]) if ex_found else None,
                new_shares=new,
                old_shares=old,
                amount=_decimal(amount_found[1]) if amount_found else None,
                currency=str(currency_found[1]).strip() if currency_found else None,
                special=special,
                page=page,
                label=json.dumps({k: item[k] for k in sorted(item)}, default=str)[:200],
            )
        )
    return ParsedPages(items=tuple(actions), errors=tuple(errors), pages=len(payloads))


def parse_statements(payloads: Sequence[bytes]) -> ParsedPages[StatementRow]:
    """Fundamental statements with their timestamps and the field names that supplied them."""
    raw_rows, errors = _pages(payloads, "statements")
    statements: list[StatementRow] = []
    for page, item in raw_rows:
        assert isinstance(item, dict)
        period_found = _first(item, "period_end", "periodEnd", "date", "fiscal_period_end")
        filed_found = _first(
            item, "filed_at", "filingDate", "filing_date", "acceptedDate", "accepted_date"
        )
        known_found = _first(item, "first_known_at", "available_at", "firstKnownAt")
        type_found = _first(item, "period_type", "period", "periodType")
        currency_found = _first(item, "currency", "reported_currency")
        raw_items = item.get("items")
        values: dict[str, Decimal] = {}
        if isinstance(raw_items, dict):
            for name, value in raw_items.items():
                parsed = _decimal(value)
                if parsed is not None:
                    values[str(name)] = parsed
        elif raw_items is not None:
            errors.append(f"page {page}: 'items' is {type(raw_items).__name__}, expected object")
        restated = item.get("restated")
        statements.append(
            StatementRow(
                period_end=parse_date(period_found[1]) if period_found else None,
                period_type=str(type_found[1]).strip().lower() if type_found else None,
                filed_at=parse_timestamp(filed_found[1]) if filed_found else None,
                filed_at_field=filed_found[0] if filed_found else None,
                first_known_at=parse_timestamp(known_found[1]) if known_found else None,
                first_known_field=known_found[0] if known_found else None,
                revision=_int(item.get("revision", item.get("revision_sequence"))),
                restated=bool(restated) if isinstance(restated, bool) else None,
                currency=str(currency_found[1]).strip() if currency_found else None,
                items=values,
                page=page,
            )
        )
    return ParsedPages(items=tuple(statements), errors=tuple(errors), pages=len(payloads))
