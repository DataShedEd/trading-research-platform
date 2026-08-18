"""Raw EODHD payloads -> canonical records. Deterministic, re-runnable, loud about rejects.

Numeric fidelity: JSON is decoded with ``parse_float=Decimal`` so a quoted ``14.27``
becomes exactly ``Decimal("14.27")`` — never a float round trip (DEC-005).

Units, deliberately preserved: EODHD quotes LSE prices in **pence** (bars get
``currency="GBX"``) but reports LSE dividends in **pounds** (their ``currency`` field,
kept verbatim). The mismatch is real and staying visible is the point (QNT-017's policy).

Corporate actions carry no announcement timestamps at EODHD, so ``available_at`` is the
DEC-007 conservative imputation (start of ex-date, flagged) via the domain model.

Every transform returns ``(records, rejects)``: a row that fails domain validation is
reported with its offending values, never silently dropped — a batch that shrinks
silently is how survivorship bias gets back in through the side door.
"""

import json
from datetime import UTC, datetime
from decimal import Decimal
from fractions import Fraction

from trp.domain.corporate_actions import Dividend, Split
from trp.domain.identifiers import SecurityId
from trp.domain.prices import DailyBar

_SOURCE = "eodhd"


def _decode(payload: bytes) -> tuple[list[dict[str, object]], list[str]]:
    try:
        document = json.loads(payload, parse_float=Decimal)
    except (json.JSONDecodeError, UnicodeDecodeError) as exc:
        return [], [f"payload not valid JSON: {exc}"]
    if not isinstance(document, list):
        return [], [f"expected top-level array, got {type(document).__name__}"]
    rows = [row for row in document if isinstance(row, dict)]
    errors = [] if len(rows) == len(document) else [f"{len(document) - len(rows)} non-object rows"]
    return rows, errors


def bars_from_eodhd(
    payload: bytes,
    security_id: SecurityId,
    *,
    currency: str,
    ingested_at: datetime,
) -> tuple[list[DailyBar], list[str]]:
    rows, rejects = _decode(payload)
    bars: list[DailyBar] = []
    for row in rows:
        try:
            bars.append(
                DailyBar(
                    security_id=security_id,
                    trade_date=row.get("date"),  # type: ignore[arg-type]
                    open=row.get("open"),  # type: ignore[arg-type]
                    high=row.get("high"),  # type: ignore[arg-type]
                    low=row.get("low"),  # type: ignore[arg-type]
                    close=row.get("close"),  # type: ignore[arg-type]
                    volume=row.get("volume"),  # type: ignore[arg-type]
                    currency=currency,
                    source=_SOURCE,
                    ingested_at=ingested_at,
                    provider_adjusted_close=row.get("adjusted_close"),  # type: ignore[arg-type]
                )
            )
        except Exception as exc:
            rejects.append(f"bar {row.get('date')}: {_short(exc)} (row={_trim(row)})")
    return bars, rejects


def splits_from_eodhd(payload: bytes, security_id: SecurityId) -> tuple[list[Split], list[str]]:
    rows, rejects = _decode(payload)
    splits: list[Split] = []
    for row in rows:
        try:
            ratio_text = str(row.get("split", "")).strip()
            new_text, _, old_text = ratio_text.partition("/")
            ratio = Fraction(Decimal(new_text)) / Fraction(Decimal(old_text))
            splits.append(
                Split(
                    security_id=security_id,
                    ex_date=row.get("date"),  # type: ignore[arg-type]
                    source=_SOURCE,
                    available_at=None,  # type: ignore[arg-type] # DEC-007 imputation
                    new_shares=ratio.numerator,
                    old_shares=ratio.denominator,
                )
            )
        except Exception as exc:
            rejects.append(f"split {row.get('date')}: {_short(exc)} (row={_trim(row)})")
    return splits, rejects


def dividends_from_eodhd(
    payload: bytes, security_id: SecurityId
) -> tuple[list[Dividend], list[str]]:
    rows, rejects = _decode(payload)
    dividends: list[Dividend] = []
    for row in rows:
        try:
            dividends.append(
                Dividend(
                    security_id=security_id,
                    ex_date=row.get("date"),  # type: ignore[arg-type]
                    record_date=row.get("recordDate") or None,  # type: ignore[arg-type]
                    pay_date=row.get("paymentDate") or None,  # type: ignore[arg-type]
                    source=_SOURCE,
                    available_at=None,  # type: ignore[arg-type] # DEC-007 imputation
                    amount=row.get("value"),  # type: ignore[arg-type]
                    # No fallback: a dividend without a currency fails validation and is
                    # reported as a reject — the unit trap must never be papered over.
                    currency=str(row.get("currency") or "").strip(),
                )
            )
        except Exception as exc:
            rejects.append(f"dividend {row.get('date')}: {_short(exc)} (row={_trim(row)})")
    return dividends, rejects


def _short(exc: Exception) -> str:
    text = str(exc).replace("\n", " ")
    return text[:160]


def _trim(row: dict[str, object]) -> str:
    return json.dumps({k: str(v) for k, v in list(row.items())[:6]})[:160]


def now_utc() -> datetime:
    return datetime.now(UTC)
