"""EODHD fundamentals: backfill, mapping verification, canonicalisation (QNT-097).

Three stages, each runnable alone::

    uv run python -m trp.canonical.fundamentals.ingest_eodhd backfill      # fetch raw
    uv run python -m trp.canonical.fundamentals.ingest_eodhd verify        # evidence report
    uv run python -m trp.canonical.fundamentals.ingest_eodhd canonicalise  # write store

Availability (DEC-007, load-bearing here): EODHD's UK ``filing_date`` is a period-end
default for ~99% of rows (bake-off finding). A filing_date is trusted only when it is
MEANINGFULLY after the period end (more than FILING_TRUST_GAP days); otherwise
``available_at`` is imputed conservatively as period end plus the documented UK lag —
120 days for annuals, 90 for interims — and flagged with the rule.

Mapping discipline: only entries whose ``review_status`` is ``verified`` in
``mappings/eodhd.json`` produce canonical rows. The ``verify`` stage prints, for every
entry, how many payload rows carry the field and a magnitude profile — the evidence a
human promotion of the entry cites. Unverified mappings are the failure mode this module
refuses to hide.
"""

import json
import logging
import time as time_module
from collections import Counter
from datetime import UTC, date, datetime, time, timedelta
from decimal import Decimal, InvalidOperation

from trp.canonical.fundamentals.normalisation import (
    ProviderLineItem,
    normalise_line_items,
    to_fundamental_value,
)
from trp.canonical.fundamentals.taxonomy import ReviewStatus, default_mapping_table
from trp.domain.fundamentals import (
    FundamentalValue,
    PeriodType,
    StatementType,
    conservative_available_at,
)
from trp.domain.identifiers import SecurityId

logger = logging.getLogger(__name__)

STATEMENTS = {
    "Income_Statement": StatementType.INCOME,
    "Balance_Sheet": StatementType.BALANCE,
    "Cash_Flow": StatementType.CASH_FLOW,
}
CADENCES = {"yearly": PeriodType.ANNUAL, "quarterly": PeriodType.INTERIM}
"""EODHD's 'quarterly' bucket holds UK half-yearly reports: INTERIM, not QUARTERLY."""

FILING_TRUST_GAP = timedelta(days=5)
"""A filing_date within this of the period end is the vendor's default, not a filing."""

UK_LAG = {PeriodType.ANNUAL: timedelta(days=120), PeriodType.INTERIM: timedelta(days=90)}
"""DEC-007 conservative UK reporting lags (DTR limits are 4 months annual, 3 interim)."""

_ENVELOPE_KEYS = frozenset({"date", "filing_date", "currency_symbol"})


class FundamentalsIngestError(Exception):
    pass


def statement_periods(
    payload: dict,  # type: ignore[type-arg]
) -> list[tuple[StatementType, PeriodType, date, datetime | None, str, list[ProviderLineItem]]]:
    """Every (statement, period) in a payload with its envelope facts and line items.

    Returns (statement, period_type, period_end, trusted_filed_at, currency, items).
    Null values are absent facts and are dropped; unparseable values raise — silent
    coercion is banned."""
    out = []
    financials = payload.get("Financials", {})
    for section, statement in STATEMENTS.items():
        # Older rows (pre-~2023 for most LSE names) carry no per-row currency_symbol;
        # the statement-level envelope declares one for the whole statement and is the
        # vendor's claim of record for those rows.
        section_currency = str(financials.get(section, {}).get("currency_symbol") or "")
        for cadence, period_type in CADENCES.items():
            for period_key, row in sorted(financials.get(section, {}).get(cadence, {}).items()):
                if not isinstance(row, dict):
                    continue
                period_end = date.fromisoformat(str(row.get("date") or period_key))
                currency = str(row.get("currency_symbol") or section_currency).upper()
                if len(currency) != 3:
                    continue  # no reporting currency anywhere: cannot be stored honestly
                filed_at = _trusted_filing(row.get("filing_date"), period_end)
                items = []
                for name, value in row.items():
                    if name in _ENVELOPE_KEYS or value is None:
                        continue
                    try:
                        decimal_value = Decimal(str(value))
                    except InvalidOperation as error:
                        raise FundamentalsIngestError(
                            f"{section}/{cadence}/{period_end}: {name}={value!r} is not a number"
                        ) from error
                    items.append(
                        ProviderLineItem(statement=statement, name=name, value=decimal_value)
                    )
                if items:
                    out.append((statement, period_type, period_end, filed_at, currency, items))
    return out


def _trusted_filing(raw: object, period_end: date) -> datetime | None:
    if not raw:
        return None
    try:
        filed = date.fromisoformat(str(raw))
    except ValueError:
        return None
    if filed - period_end <= FILING_TRUST_GAP:
        return None  # the vendor's period-end default, not a real filing date
    return datetime.combine(filed, time.min, tzinfo=UTC)


def availability(
    period_end: date, period_type: PeriodType, filed_at: datetime | None
) -> tuple[datetime, bool, str | None]:
    if filed_at is not None:
        return filed_at, False, None
    lag = UK_LAG[period_type]
    rule = f"period_end+{lag.days}d (UK {period_type.value}, DEC-007)"
    return conservative_available_at(period_end, lag), True, rule


# ---------------------------------------------------------------------------- stages


def _archived_symbols(store) -> dict[str, object]:  # type: ignore[no-untyped-def]
    from trp.providers.base import Dataset

    out: dict[str, object] = {}
    for meta in store.records(provider="eodhd", dataset=Dataset.FUNDAMENTALS):
        record, _content = store.read(meta)
        out[str(record.params.get("symbol"))] = meta
    return out


def backfill(*, pace_seconds: float = 0.3) -> None:
    from trp.canonical.security_store import read_security_master
    from trp.config import load_settings
    from trp.ingestion.raw import RawStore
    from trp.providers.adapters.eodhd import EodhdProvider
    from trp.providers.base import Dataset
    from trp.universe.ftse_build import _eodhd_code_pairs

    settings = load_settings()
    store = RawStore(settings.raw_dir)
    provider = EodhdProvider()
    master = read_security_master(settings.canonical_dir / "securities")
    pairs = _eodhd_code_pairs(master)
    already = set(_archived_symbols(store))
    fetched = skipped = 0
    for _security_id, code in pairs:
        symbol = f"{code.partition('.')[0]}:XLON"
        if symbol in already:
            skipped += 1
            continue
        for page in provider.fundamentals(symbol):
            store.write("eodhd", provider.version, Dataset.FUNDAMENTALS, page)
        fetched += 1
        already.add(symbol)
        time_module.sleep(pace_seconds)
        if fetched % 25 == 0:
            print(f"...fetched {fetched}", flush=True)
    print(f"backfill: {fetched} fetched, {skipped} already archived, {len(pairs)} code-pairs")


def verify() -> None:
    """Evidence for mapping promotion: per provider_item, how often it appears with a
    value across every archived payload, and the magnitude profile."""
    from trp.config import load_settings
    from trp.ingestion.raw import RawStore

    settings = load_settings()
    store = RawStore(settings.raw_dir)
    counts: Counter[tuple[str, str]] = Counter()
    magnitudes: dict[tuple[str, str], list[float]] = {}
    payloads = 0
    for _symbol, meta in sorted(_archived_symbols(store).items()):
        _record, content = store.read(meta)  # type: ignore[arg-type]
        if content is None:
            continue
        payloads += 1
        for statement, _pt, _pe, _fa, _ccy, items in statement_periods(json.loads(content)):
            for item in items:
                key = (statement.value, item.name)
                counts[key] += 1
                magnitudes.setdefault(key, []).append(abs(float(item.value)))
    table = default_mapping_table("eodhd")
    print(f"{payloads} payloads scanned\n")
    print(f"{'statement':<10} {'provider_item':<38} {'rows':>7}  median_abs   status")
    for entry in sorted(table.entries, key=lambda e: (e.statement.value, e.provider_item)):
        key = (entry.statement.value, entry.provider_item)
        rows = counts.get(key, 0)
        values = sorted(magnitudes.get(key, []))
        median = values[len(values) // 2] if values else 0.0
        print(
            f"{entry.statement.value:<10} {entry.provider_item:<38} {rows:>7}  "
            f"{median:>10.3g}   {entry.review_status.value}"
        )
    mapped_keys = {(e.statement.value, e.provider_item) for e in table.entries}
    unmapped = Counter(key for key in counts if key not in mapped_keys)
    frequent_unmapped = [
        (key, counts[key]) for key in sorted(unmapped, key=lambda k: -counts[k])[:25]
    ]
    print("\nmost frequent unmapped provider items:")
    for (statement_name, name), n in frequent_unmapped:
        print(f"  {statement_name:<10} {name:<40} {n}")


def canonicalise() -> None:
    from trp.canonical.fundamentals.storage import write_fundamentals
    from trp.canonical.security_store import read_security_master
    from trp.config import load_settings
    from trp.ingestion.raw import RawStore
    from trp.universe.ftse_build import _eodhd_code_pairs

    settings = load_settings()
    store = RawStore(settings.raw_dir)
    master = read_security_master(settings.canonical_dir / "securities")
    by_symbol = {f"{code.partition('.')[0]}:XLON": sid for sid, code in _eodhd_code_pairs(master)}
    table = default_mapping_table("eodhd")
    verified = {
        (e.statement, e.provider_item)
        for e in table.entries
        if e.review_status is ReviewStatus.VERIFIED
    }
    if not verified:
        raise FundamentalsIngestError(
            "no verified mapping entries — run `verify`, review the evidence, and promote "
            "entries in mappings/eodhd.json before canonicalising"
        )
    records: list[FundamentalValue] = []
    payloads = missing = 0
    unmapped_counter: Counter[str] = Counter()
    for symbol, meta in sorted(_archived_symbols(store).items()):
        security_id = by_symbol.get(symbol)
        _record, content = store.read(meta)  # type: ignore[arg-type]
        if security_id is None or content is None:
            missing += 1
            continue
        payloads += 1
        for _statement, period_type, period_end, filed_at, currency, items in statement_periods(
            json.loads(content)
        ):
            keep = [i for i in items if (i.statement, i.name) in verified]
            if not keep:
                unmapped_counter.update(i.name for i in items)
                continue
            result = normalise_line_items(keep, provider="eodhd")
            available_at, imputed, rule = availability(period_end, period_type, filed_at)
            for item in result.mapped:
                records.append(
                    to_fundamental_value(
                        item,
                        security_id=SecurityId(security_id),
                        period_end=period_end,
                        period_type=period_type,
                        currency=currency,
                        available_at=available_at,
                        filed_at=filed_at,
                        availability_imputed=imputed,
                        imputation_rule=rule,
                        source="eodhd",
                    )
                )
    written = write_fundamentals(
        records, settings.canonical_dir / "fundamentals", source="eodhd-qnt-097"
    )
    imputed_share = sum(1 for r in records if r.availability_imputed) / max(1, len(records))
    print(
        f"canonicalise: {payloads} payloads -> {len(records)} records, {written} written "
        f"({imputed_share:.1%} DEC-007 imputed); {missing} symbols without master mapping"
    )


if __name__ == "__main__":
    import sys

    from trp.logging import setup_logging

    setup_logging()
    stage = sys.argv[1] if len(sys.argv) > 1 else "verify"
    {"backfill": backfill, "verify": verify, "canonicalise": canonicalise}[stage]()
