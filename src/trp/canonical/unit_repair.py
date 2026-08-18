"""GBX/GBP quotation-unit repair for canonical LSE prices and dividends (QNT-093).

EODHD serves LSE history with inconsistent units: most tickers in GBX (pence), some whole
series in GBP (Compass at 12.28 meaning £12.28), and some series flipping unit for
segments (Just Eat June 2022, Thomas Cook 2007-08). Dividend amounts carry the same
disease per record. This module detects and repairs both, with evidence, and fails loudly
on anything it cannot classify.

Price repair, per security:
1. CONTINUITY: a one-day close ratio inside [1/RATIO_BAND_HIGH, 1/RATIO_BAND_LOW] or
   [RATIO_BAND_LOW, RATIO_BAND_HIGH] is a unit flip (real one-day moves are never a clean
   ~100x); every subsequent bar is rescaled so the series is continuous in its LEADING
   unit. Open/high/low/close scale together; volume never does.
2. GLOBAL UNIT: decide whether the (now continuous) series is GBX or GBP.
   - Dividend evidence: EODHD LSE dividends are GBP-stated by default, so annual dividend
     x 100 over median close lands near a real yield (0-15%) for a GBX series and near
     100x that for a GBP series.
   - Level evidence: a FTSE-100-ever name whose median close is below GBP_LEVEL_CEILING
     is a GBP series (no FTSE 100 member's pence median has ever been that low).
   - Agreement or a single decisive signal classifies; conflict or no signal lands the
     security in ``unresolved`` unless it has an ``ADJUDICATED`` entry, and any unresolved
     security blocks the write.

Dividend repair, per record (against REPAIRED prices): default GBP; if the GBP reading
implies a single-payment yield above SINGLE_PAYMENT_YIELD_CEILING while the GBX reading
is plausible, the record was GBX-stated — relabel it. Records implausible under BOTH
readings are reported.

The store is append-only, so repaired bars are written as a full new dataset under
``source="eodhd-gbx"`` (originals untouched); repaired dividends go to a new parquet next
to the original; a JSON report records every decision.
"""

import json
import logging
from dataclasses import dataclass, field
from datetime import UTC, datetime
from decimal import Decimal
from fractions import Fraction

import polars as pl

logger = logging.getLogger(__name__)

REPAIRED_SOURCE = "eodhd-gbx"

RATIO_BAND_LOW = 70
RATIO_BAND_HIGH = 140
"""A one-day close ratio in [70, 140] (or its inverse) is a unit flip, not a price move."""

GBP_LEVEL_CEILING = Decimal("25")
"""A FTSE-100-ever median close below 25 in its leading unit means that unit is GBP."""

SERIES_YIELD_GBP_THRESHOLD = 0.30
"""Median annual (dividend x 100 / close) above this marks a GBP-priced series."""

SERIES_YIELD_GBX_CEILING = 0.15
"""...and below this marks a GBX-priced series; between the two is a conflict."""

SINGLE_PAYMENT_YIELD_CEILING = 0.25
"""A single dividend above 25% of price under the GBP reading is suspect."""

PENCE_SCALE_FLOOR = Decimal("2")
"""Relabel GBP -> GBX only when the amount is also implausibly large for pounds
(UK single payments above £2/share are essentially unheard of, while 2-60 pence is the
normal range). A high GBP-reading yield with a sub-£2 amount is a genuine crash-era
dividend (Segro April 2009), kept as GBP and reported, never shrunk."""

ADJUDICATED_PRICE_UNITS: dict[str, tuple[int, str]] = {}
"""security_id -> (scale to apply after continuity, reason). Filled only by human review."""


class UnitRepairError(Exception):
    pass


@dataclass
class SecurityRepair:
    security_id: str
    flips: list[str] = field(default_factory=list)  # ISO dates where the unit flipped
    global_scale: int = 1  # multiplier applied to the whole (continuity-repaired) series
    evidence: str = ""


@dataclass
class RepairReport:
    securities: list[SecurityRepair] = field(default_factory=list)
    unresolved: list[str] = field(default_factory=list)
    dividends_relabelled_gbx: int = 0
    dividends_implausible: list[str] = field(default_factory=list)
    dividends_high_yield_kept: list[str] = field(default_factory=list)

    def changed(self) -> list[SecurityRepair]:
        return [s for s in self.securities if s.flips or s.global_scale != 1]

    def to_json(self) -> str:
        return json.dumps(
            {
                "repaired_at": datetime.now(UTC).isoformat(),
                "changed": [
                    {
                        "security_id": s.security_id,
                        "flips": s.flips,
                        "global_scale": s.global_scale,
                        "evidence": s.evidence,
                    }
                    for s in self.changed()
                ],
                "unresolved": self.unresolved,
                "dividends_relabelled_gbx": self.dividends_relabelled_gbx,
                "dividends_implausible": self.dividends_implausible,
                "dividends_high_yield_kept": self.dividends_high_yield_kept,
            },
            indent=2,
        )


def _is_flip(ratio: Fraction) -> int:
    """0 = no flip; +1 = unit became 100x smaller (x100 to restore); -1 = 100x larger."""
    if Fraction(1, RATIO_BAND_HIGH) <= ratio <= Fraction(1, RATIO_BAND_LOW):
        return 1
    if RATIO_BAND_LOW <= ratio <= RATIO_BAND_HIGH:
        return -1
    return 0


def repair_prices(
    prices: pl.DataFrame, dividends: pl.DataFrame
) -> tuple[pl.DataFrame, RepairReport]:
    """Return (repaired frame in GBX, report). Same schema; only open/high/low/close
    change. Unresolved securities keep their original values and block any write."""
    report = RepairReport()
    out_frames: list[pl.DataFrame] = []
    # Yield evidence needs dividends in GBX: GBP-labelled records x100, GBX-labelled
    # as-is; foreign-currency records carry no GBX yield evidence and are skipped.
    annual_dividends = (
        dividends.filter(pl.col("currency").is_in(["GBP", "GBX"]))
        .with_columns(
            pl.col("ex_date").dt.year().alias("year"),
            pl.when(pl.col("currency") == "GBP")
            .then(pl.col("amount") * 100)
            .otherwise(pl.col("amount"))
            .alias("amount_gbx"),
        )
        .group_by("security_id", "year")
        .agg(pl.col("amount_gbx").sum().alias("annual_gbx"))
    )
    lattice = {Fraction(1), Fraction(100), Fraction(1, 100)}

    for key, frame in sorted(prices.partition_by("security_id", as_dict=True).items()):
        security_id = str(key[0])
        frame = frame.sort("trade_date")
        repair = SecurityRepair(security_id=security_id)
        report.securities.append(repair)
        closes = [Fraction(Decimal(str(v))) for v in frame["close"]]
        dates = frame["trade_date"].to_list()

        # 1. Continuity: row_scale[i] restores row i to the LEADING unit.
        current = Fraction(1)
        row_scale = [Fraction(1)]
        resolved = True
        for i in range(1, len(closes)):
            if closes[i - 1] > 0 and closes[i] > 0:
                flip = _is_flip(closes[i] / closes[i - 1])
                if flip:
                    current *= Fraction(100) ** flip
                    repair.flips.append(dates[i].isoformat())
                    if current not in lattice:
                        repair.evidence = f"continuity scale left the 100x lattice on {dates[i]}"
                        resolved = False
                        break
            row_scale.append(current)
        if not resolved:
            report.unresolved.append(security_id)
            out_frames.append(frame)
            continue

        # 2. Global unit of the leading segment.
        continuous = [c * s for c, s in zip(closes, row_scale, strict=True)]
        decision = _classify_global_unit(security_id, continuous, dates, annual_dividends, repair)
        if decision is None:
            report.unresolved.append(security_id)
            out_frames.append(frame)
            continue
        repair.global_scale = decision
        out_frames.append(_apply_scales(frame, [s * decision for s in row_scale]))

    repaired = pl.concat(out_frames).sort(["security_id", "trade_date"])
    return repaired, report


def _classify_global_unit(
    security_id: str,
    continuous_closes: list[Fraction],
    dates: list,  # type: ignore[type-arg]
    annual_dividends: pl.DataFrame,
    repair: SecurityRepair,
) -> int | None:
    adjudicated = ADJUDICATED_PRICE_UNITS.get(security_id)
    if adjudicated is not None:
        scale, reason = adjudicated
        repair.evidence = f"adjudicated: {reason}"
        return scale

    median_close = sorted(continuous_closes)[len(continuous_closes) // 2]
    level_says_gbp = median_close < Fraction(GBP_LEVEL_CEILING)

    security_dividends = annual_dividends.filter(pl.col("security_id") == security_id)
    yield_verdict: bool | None = None
    if security_dividends.height >= 2:
        by_year: dict[int, Fraction] = {}
        for d, c in zip(dates, continuous_closes, strict=True):
            by_year.setdefault(d.year, c)  # first close of the year is representative enough
        yields = []
        for row in security_dividends.iter_rows(named=True):
            close = by_year.get(row["year"])
            if close and close > 0:
                yields.append(float(Fraction(Decimal(str(row["annual_gbx"]))) / close))
        if yields:
            median_yield = sorted(yields)[len(yields) // 2]
            if median_yield > SERIES_YIELD_GBP_THRESHOLD:
                yield_verdict = True
            elif median_yield <= SERIES_YIELD_GBX_CEILING:
                yield_verdict = False
            repair.evidence = f"median annual GBX yield over stored close {median_yield:.3f}"

    if yield_verdict is True or (yield_verdict is None and level_says_gbp):
        repair.evidence += f"; median close {float(median_close):.2f} -> GBP series, x100"
        return 100
    if yield_verdict is False and level_says_gbp:
        repair.evidence += (
            f"; CONFLICT: yield says GBX but median close {float(median_close):.2f} < "
            f"{GBP_LEVEL_CEILING}"
        )
        return None
    repair.evidence += f"; median close {float(median_close):.2f} -> GBX series"
    return 1


def _apply_scales(frame: pl.DataFrame, scales: list[Fraction]) -> pl.DataFrame:
    if all(s == 1 for s in scales):
        return frame
    factors = pl.Series("unit_factor", [float(s) for s in scales])
    scaled = frame.with_columns(factors)
    for column in ("open", "high", "low", "close"):
        scaled = scaled.with_columns(
            (pl.col(column).cast(pl.Float64) * pl.col("unit_factor"))
            .round(6)
            .cast(frame.schema[column])
            .alias(column)
        )
    return scaled.drop("unit_factor")


def repair_dividends(
    dividends: pl.DataFrame, repaired_prices: pl.DataFrame
) -> tuple[pl.DataFrame, RepairReport]:
    """Relabel GBX-stated dividend records (against repaired GBX prices). Returns the
    full dividend frame with corrected ``currency`` and a report."""
    report = RepairReport()
    closes = repaired_prices.sort(["security_id", "trade_date"]).select(
        "security_id", "trade_date", "close"
    )
    joined = dividends.sort(["security_id", "ex_date"]).join_asof(
        closes,
        left_on="ex_date",
        right_on="trade_date",
        by="security_id",
        strategy="backward",
    )
    currencies: list[str] = []
    for row in joined.iter_rows(named=True):
        currency = row["currency"]
        close = row["close"]
        if currency != "GBP" or close is None or close == 0:
            currencies.append(currency)
            continue
        amount = float(row["amount"])
        close_f = float(close)
        gbp_yield = amount * 100 / close_f
        gbx_yield = amount / close_f
        if gbp_yield > SINGLE_PAYMENT_YIELD_CEILING and amount >= float(PENCE_SCALE_FLOOR):
            if gbx_yield <= SINGLE_PAYMENT_YIELD_CEILING:
                currencies.append("GBX")
                report.dividends_relabelled_gbx += 1
            else:
                currencies.append(currency)
                report.dividends_implausible.append(
                    f"{row['security_id']} {row['ex_date']}: amount {amount} vs close {close_f}"
                )
        elif gbp_yield > SINGLE_PAYMENT_YIELD_CEILING:
            currencies.append(currency)  # genuine crash-era yield: small amount, kept
            report.dividends_high_yield_kept.append(
                f"{row['security_id']} {row['ex_date']}: {amount} GBP on close {close_f}"
            )
        else:
            currencies.append(currency)
    out = dividends.sort(["security_id", "ex_date"]).with_columns(pl.Series("currency", currencies))
    return out, report


ADJUDICATED_SPLIT_EXCLUSIONS: dict[tuple[str, str], str] = {
    ("SEC-69669830-3371-47e7-b40a-fb8c865bf020", "2009-05-20"): (
        "Lloyds May 2009: EODHD records the HMG open offer as a 1.3096 'split'; the raw "
        "series shows a 1.86x move confounded by the capital raising. Open offers are "
        "capital events (DEC-009 territory), not splits — excluded."
    ),
    ("SEC-e9358707-dd8e-478b-b1e3-4c397410b732", "2009-04-02"): (
        "Wolseley/Ferguson April 2009: 1-for-10 consolidation simultaneous with a deeply "
        "discounted rights issue; the raw series moves 4.3x, matching neither reading. "
        "Excluded rather than guessed; pre-dates DEC-014 research coverage."
    ),
}
"""(security_id, ex_date ISO) -> reason. Grows only by human adjudication."""


def audit_splits(splits: pl.DataFrame, repaired_prices: pl.DataFrame) -> pl.DataFrame:
    """Classify each split record against the REPAIRED price series.

    REAL: the raw close gapped by ~the ratio on the ex-date. PRE_APPLIED: the close did
    not move — the vendor already scaled the surrounding history, so applying the record
    would double-count. SMALL_UNVERIFIABLE: |ratio - 1| < 25%, indistinguishable from a
    day's price move (kept; worst-case error is bounded by the ratio itself).
    NO_PRICE_CONTEXT: no bars around the ex-date (kept; it can never apply to a mark).
    UNCLEAR: price moved, but not like the ratio — human adjudication required."""
    import math

    rows: list[dict[str, object]] = []
    for r in splits.iter_rows(named=True):
        ratio = r["new_shares"] / r["old_shares"]
        series = repaired_prices.filter(pl.col("security_id") == r["security_id"]).sort(
            "trade_date"
        )
        before = series.filter(pl.col("trade_date") < r["ex_date"]).tail(1)
        after = series.filter(pl.col("trade_date") >= r["ex_date"]).head(1)
        if not (before.height and after.height):
            verdict = "NO_PRICE_CONTEXT"
            implied = None
        else:
            implied = float(before["close"][0]) / float(after["close"][0])
            if abs(math.log(ratio)) < math.log(1.25):
                verdict = "SMALL_UNVERIFIABLE"
            elif abs(math.log(implied / ratio)) < math.log(1.35):
                verdict = "REAL"
            elif abs(math.log(implied)) < math.log(1.35):
                verdict = "PRE_APPLIED"
            else:
                verdict = "UNCLEAR"
        rows.append(
            {
                "security_id": r["security_id"],
                "ex_date": r["ex_date"],
                "ratio": ratio,
                "implied": implied,
                "verdict": verdict,
            }
        )
    return pl.DataFrame(rows, infer_schema_length=None)


def repair_splits(
    splits: pl.DataFrame, repaired_prices: pl.DataFrame
) -> tuple[pl.DataFrame, pl.DataFrame]:
    """Return (kept splits, full audit). PRE_APPLIED and adjudicated records are dropped;
    UNCLEAR records without an adjudication entry raise."""
    audit = audit_splits(splits, repaired_prices)
    drop: set[tuple[str, str]] = set(ADJUDICATED_SPLIT_EXCLUSIONS)
    for row in audit.iter_rows(named=True):
        key = (row["security_id"], row["ex_date"].isoformat())
        if row["verdict"] == "PRE_APPLIED":
            drop.add(key)
        elif row["verdict"] == "UNCLEAR" and key not in drop:
            raise UnitRepairError(
                f"split {key} is UNCLEAR (implied {row['implied']:.3f} vs ratio "
                f"{row['ratio']:.3f}) and has no adjudication entry"
            )
    keys = pl.DataFrame(
        {
            "security_id": [k[0] for k in drop],
            "ex_date": [k[1] for k in drop],
        }
    ).with_columns(pl.col("ex_date").str.to_date())
    kept = splits.join(keys, on=["security_id", "ex_date"], how="anti") if drop else splits
    return kept, audit


def run_repair(*, write: bool) -> RepairReport:
    """Load canonical datasets, repair, audit — and only with ``write=True`` persist:
    repaired bars appended under ``source=REPAIRED_SOURCE`` (append-only store, originals
    untouched), repaired dividends/splits to new ``*_gbx`` parquets, and the JSON report
    beside them. Refuses to write while anything is unresolved."""
    from trp.canonical.price_store import write_prices
    from trp.canonical.prices import frame_to_bars
    from trp.config import load_settings

    settings = load_settings()
    actions_dir = settings.canonical_dir / "corporate_actions"
    prices_root = settings.canonical_dir / "prices"
    prices = pl.concat([pl.read_parquet(f) for f in sorted(prices_root.rglob("part-*.parquet"))])
    original = prices.filter(pl.col("source") != REPAIRED_SOURCE)
    dividends = pl.read_parquet(actions_dir / "eodhd_ftse100_dividends.parquet")
    splits = pl.read_parquet(actions_dir / "eodhd_ftse100_splits.parquet")

    repaired, report = repair_prices(original, dividends)
    if report.unresolved:
        raise UnitRepairError(f"unresolved securities: {report.unresolved}")
    repaired_dividends, dividend_report = repair_dividends(dividends, repaired)
    if dividend_report.dividends_implausible:
        raise UnitRepairError(f"implausible dividends: {dividend_report.dividends_implausible}")
    report.dividends_relabelled_gbx = dividend_report.dividends_relabelled_gbx
    report.dividends_high_yield_kept = dividend_report.dividends_high_yield_kept
    kept_splits, split_audit = repair_splits(splits, repaired)

    logger.info(
        "repair: %d securities changed, %d dividend relabels, %d splits dropped",
        len(report.changed()),
        report.dividends_relabelled_gbx,
        splits.height - kept_splits.height,
    )
    if not write:
        return report

    report_path = actions_dir / "unit_repair_report.json"
    dividends_path = actions_dir / "eodhd_ftse100_dividends_gbx.parquet"
    splits_path = actions_dir / "eodhd_ftse100_splits_gbx.parquet"
    for path in (report_path, dividends_path, splits_path):
        if path.exists():
            raise UnitRepairError(f"{path} exists; repairs are never overwritten")

    now = datetime.now(UTC)
    bars = frame_to_bars(
        repaired.with_columns(
            pl.lit(REPAIRED_SOURCE).alias("source"),
            pl.lit(now).alias("ingested_at"),
        )
    )
    written = write_prices(bars, prices_root, source="unit-repair-qnt-093")
    logger.info("wrote %d repaired bars under source=%s", written, REPAIRED_SOURCE)
    repaired_dividends.write_parquet(dividends_path)
    kept_splits.write_parquet(splits_path)
    payload = json.loads(report.to_json())
    payload["split_audit"] = split_audit.with_columns(pl.col("ex_date").cast(pl.Utf8)).to_dicts()
    payload["splits_dropped"] = splits.height - kept_splits.height
    report_path.write_text(json.dumps(payload, indent=2))
    return report


if __name__ == "__main__":
    import sys

    from trp.logging import setup_logging

    setup_logging()
    run_repair(write="--write" in sys.argv)
