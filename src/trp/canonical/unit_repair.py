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

ORIGINAL_SOURCE = "eodhd"
REPAIRED_SOURCE = "eodhd-gbx3"
"""Bumped when adjudications change the repaired values: the store is append-only, so a
re-adjudication is a NEW full dataset under a new source, never an edit. gbx (v1) had
Melrose's whole series x100; gbx2 added the segment adjudication below; gbx3
(2026-08-21, DEC-028) is the QNT-111/112 generic-defect release: windowed multi-code
attribution (the arbitrary ATST/ALW and SPD/FRAS payload blends were a defect),
single-bar vendor-spike filtering, sentinel-bar removal, and the FTSE 250 extension
adjudications. The FTSE 100 canonical baseline was RE-RUN under gbx3 per the frozen
directive's defect protocol; prior run records are preserved."""

DIVIDENDS_FILE = "eodhd_ftse100_dividends_gbx3.parquet"
SPLITS_FILE = "eodhd_ftse100_splits_gbx3.parquet"
REPORT_FILE = "unit_repair_report_gbx3.json"

ADJUDICATED_SEGMENT_SCALES: dict[str, list[tuple[str, int]]] = {
    # Melrose: vendor basis changes at the April 2023 Dowlais demerger + consolidation.
    # Raw closes AFTER 2023-04-21 are GBX-native (404.35 on 2023-04-24 vs the real
    # ~404p tape), so the classifier's whole-series x100 must stop there; the earlier
    # era keeps x100 (a consistently scaled series is harmless for within-era ratios,
    # and Melrose stays on the market-value exclusion list regardless).
    "SEC-fa995f37-4006-480f-b273-410aa6790c12": [("2023-04-22", 1)],
}
"""security_id -> [(from_date ISO, global scale override)]. Grows only by human review."""

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
OUT_OF_FAMILY_SCALE = 20
"""Relabel GBP -> GBX only when the amount is also implausibly large for pounds
(UK single payments above £2/share are essentially unheard of, while 2-60 pence is the
normal range). A high GBP-reading yield with a sub-£2 amount is a genuine crash-era
dividend (Segro April 2009), kept as GBP and reported, never shrunk."""

ADJUDICATED_PRICE_UNITS: dict[str, tuple[int, str]] = {
    # QNT-111 FTSE 250 extension — three series where yield evidence and price level
    # are jointly inconclusive; adjudicated GBX-throughout (scale 1) against known
    # trading ranges:
    "SEC-0da28726-7cda-42bb-9912-7091e1b7b887": (
        1,
        "Pan African Resources: GBX throughout — sub-10p microcap era (2000s) through "
        "~130p in the 2025-26 gold rally; £2.5bn at its Dec 2025 FTSE 250 entry is "
        "consistent with the index boundary",
    ),
    "SEC-8edebc68-26be-499f-b05b-3f56ed31a5d3": (
        1,
        "Galliford Try: GBX throughout — pre-1998 single-digit-pence era is genuine "
        "(pre-consolidation smallcap), ~600p current is the real trading range",
    ),
    "SEC-971b50c9-df35-4d7c-ba54-fe26759dc543": (
        1,
        "Amigo Holdings: GBX throughout — 286.5p at the 2018 IPO collapsing to "
        "sub-penny is the real, notorious path",
    ),
    "SEC-52c3b129-0a43-4cb8-a29e-d2920a23b8af": (
        100,
        "Hastings Group Holdings: EODHD serves the post-IPO series in POUNDS "
        "(0.75-3.3 vs the real 75-330p range); dividends are pence — scale x100 "
        "(pre-IPO rows separately excluded, see ADJUDICATED_BAR_EXCLUSIONS)",
    ),
}
"""security_id -> (scale to apply after continuity, reason). Filled only by human review."""


ADJUDICATED_BAR_EXCLUSIONS: dict[str, tuple[str, str]] = {
    # security_id -> (exclude bars strictly BEFORE this ISO date, reason). Original
    # rows are retained in the append-only store; the exclusion applies to the
    # REPAIRED dataset research consumers read. May only shrink.
    "SEC-52c3b129-0a43-4cb8-a29e-d2920a23b8af": (
        "2015-10-01",
        "Hastings Group Holdings IPO'd October 2015; EODHD's HSTG.LSE series carries "
        "2001-2015 rows from an unrelated/garbage line (closes 0.0001-12) that would "
        "poison momentum lookbacks",
    ),
    "SEC-1503bea0-6abf-4be9-9850-c18484b336e9": (
        "2009-11-02",
        "Genesis Emerging Markets Fund: quoted in USD before the November 2009 "
        "10-for-1 subdivision and GBX line switch; pre-switch bars are in a different "
        "currency regime and are excluded rather than mis-adjusted",
    ),
    "SEC-75afce23-86bb-440c-9233-7292574fff6e": (
        "2010-01-04",
        "Bankers Investment Trust: a 10-for-1 subdivision took effect on the first "
        "session of 2010 (3650p -> 369p) but EODHD carries no split record for it; "
        "rather than fabricate one, pre-subdivision bars are excluded — windows never "
        "span the boundary and Bankers is INSUFFICIENT_DATA until January 2011, the "
        "conservative outcome",
    ),
    "SEC-51cfae69-e197-44a6-8dee-f158315f45f1": (
        "2020-05-28",
        "Hyve Group: the May 2020 rights-issue + 10:1 consolidation boundary cannot "
        "be adjusted honestly (see the split exclusion); pre-boundary bars are "
        "excluded so momentum windows never span the artificial jump — Hyve then has "
        "insufficient history until mid-2021 and is INSUFFICIENT_DATA, the "
        "conservative outcome",
    ),
}

ADJUDICATED_DIVIDEND_EXCLUSIONS: dict[tuple[str, str], str] = {
    # (security_id, ex_date) -> reason. Dropped from the repaired dividends dataset.
    ("SEC-7df3206e-54a5-4015-9b76-0b5231df7967", "2022-08-03"): (
        "City of London Investment Trust: vendor records a 364.265p dividend against a "
        "414.5p close — CTY pays ~5p quarterlies; the record is corrupt (no such "
        "distribution exists)"
    ),
}


SPIKE_RATIO = 8
"""A close that jumps by more than this AND reverts within two bars is a vendor
artefact (e.g. EODHD's 2012-05-28 sentinel day: literal 1,000,000.0 closes across
several investment trusts), never a market move or a corporate action — real
consolidations do not revert. Dropped from the repaired dataset with a log line."""


def drop_single_bar_spikes(original: pl.DataFrame) -> tuple[pl.DataFrame, list[str]]:
    """Remove single-bar price spikes that revert immediately (vendor artefacts)."""
    log: list[str] = []
    drop_keys: list[tuple[str, object]] = []
    for (sid,), group in original.group_by("security_id"):
        g = group.sort("trade_date")
        closes = [float(v) for v in g["close"].to_list()]
        dates = g["trade_date"].to_list()
        for i in range(1, len(closes) - 1):
            prev_close, this_close = closes[i - 1], closes[i]
            if prev_close <= 0 or this_close <= 0:
                continue
            ratio = this_close / prev_close
            if ratio > SPIKE_RATIO or ratio < 1 / SPIKE_RATIO:
                after = closes[i + 1]
                if after > 0 and 0.5 < after / prev_close < 2.0:
                    drop_keys.append((str(sid), dates[i]))
                    log.append(
                        f"{sid} {dates[i]}: single-bar spike {this_close} between "
                        f"{prev_close} and {after} — vendor artefact dropped"
                    )
    if not drop_keys:
        return original, log
    keys = pl.DataFrame(
        {
            "security_id": [k[0] for k in drop_keys],
            "trade_date": [k[1] for k in drop_keys],
        },
        schema={"security_id": pl.Utf8, "trade_date": pl.Date},
    )
    return original.join(keys, on=["security_id", "trade_date"], how="anti"), log


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
        segments = ADJUDICATED_SEGMENT_SCALES.get(security_id, [])
        if segments:
            from datetime import date as date_type

            boundaries = [(date_type.fromisoformat(d), scale) for d, scale in segments]
            per_row = []
            for row_date, base in zip(dates, row_scale, strict=True):
                scale = decision
                for boundary, override in boundaries:
                    if row_date >= boundary:
                        scale = override
                per_row.append(base * scale)
            repair.evidence += f"; segment adjudication {segments}"
            out_frames.append(_apply_scales(frame, per_row))
        else:
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
    # Per-security median GBP-labelled amount: an amount >= OUT_OF_FAMILY_SCALE x the
    # security's own median with a >25% implied yield is a per-record 100x mis-scale
    # (UK Commercial Property Trust prints 0.92 GBP for eleven quarters where its real
    # dividend is 0.92p) — distinct from a genuine one-off crash-era yield (Segro 2009),
    # whose amount sits INSIDE the security's normal family.
    family_median = {
        row["security_id"]: float(row["median"])
        for row in dividends.filter(pl.col("currency") == "GBP")
        .group_by("security_id")
        .agg(pl.col("amount").cast(pl.Float64).median().alias("median"))
        .iter_rows(named=True)
    }
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
        median = family_median.get(row["security_id"], 0.0)
        out_of_family = median > 0 and amount >= OUT_OF_FAMILY_SCALE * median
        if gbp_yield > SINGLE_PAYMENT_YIELD_CEILING and (
            amount >= float(PENCE_SCALE_FLOOR) or out_of_family
        ):
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
    ("SEC-1503bea0-6abf-4be9-9850-c18484b336e9", "2009-11-02"): (
        "Genesis Emerging Markets Fund November 2009: 10-for-1 subdivision simultaneous "
        "with the quote line moving from USD to GBX (raw move 16.48x = 10 x ~1.65 "
        "USD/GBP). Pre-2009-11-02 bars are excluded (see ADJUDICATED_BAR_EXCLUSIONS), "
        "so no split adjustment is needed at the series boundary."
    ),
    ("SEC-31459bb7-b11b-4601-bf31-247f711fa0e1", "2000-10-02"): (
        "Coats October 2000: recorded 20:1 vs observed 12.7x — consolidation entangled "
        "with a corporate event in the pre-coverage era. No research window spans "
        "October 2000 (coverage starts 2009+; Coats' modern membership era begins "
        "2015), so the residual jump is outside every momentum lookback. Excluded."
    ),
    ("SEC-51cfae69-e197-44a6-8dee-f158315f45f1", "2020-05-28"): (
        "Hyve May 2020: 10:1 consolidation simultaneous with the deeply discounted "
        "COVID rights issue (observed 5.9x matches neither reading — the Wolseley "
        "class). Excluded; Hyve's pre-consolidation bars are also excluded (see "
        "ADJUDICATED_BAR_EXCLUSIONS) so no window spans the artificial boundary."
    ),
    ("SEC-636ce1b1-7eba-466e-91fc-562300dc3814", "2019-06-07"): (
        "PV Crystalox June 2019: recorded 22:1 vs observed 2.3x (return of capital + "
        "consolidation). The company left the FTSE 250 in 2011; no member-window "
        "computation ever reads bars spanning this date. Excluded."
    ),
    ("SEC-89b0b8af-b88f-41cd-8c15-62c83d9924c8", "2000-08-18"): (
        "Mothercare August 2000: recorded 5:1 vs observed 3.0x (demerger-era event, "
        "pre-coverage). No research window spans August 2000. Excluded."
    ),
    ("SEC-ce5da080-f4ca-47ec-ad50-0ca836a72686", "2024-04-23"): (
        "Pinewood Technologies (ex-Pendragon) April 2024: 20:1 consolidation "
        "simultaneous with the motor-business disposal capital return (observed 8x). "
        "Pinewood's FTSE 250 membership starts September 2025; 12-1 windows from then "
        "reach back to September 2024, after this event. Excluded."
    ),
    ("SEC-156d483f-0249-4e65-b965-7542685d0aea", "2018-08-02"): (
        "Countrywide August 2018: EODHD records the firm placing/open offer (502:283) "
        "as a split; the 2.69x price fall is genuine dilution from the ~10p capital "
        "raising, not a share subdivision. Capital events are not adjusted (DEC-009) — "
        "excluded. The separate 1-for-50 consolidation (2019-12-30) is real and kept."
    ),
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
    unclear: list[str] = []
    for row in audit.iter_rows(named=True):
        key = (row["security_id"], row["ex_date"].isoformat())
        if row["verdict"] == "PRE_APPLIED":
            drop.add(key)
        elif row["verdict"] == "UNCLEAR" and key not in drop:
            unclear.append(f"{key} implied {row['implied']:.3f} vs ratio {row['ratio']:.3f}")
    if unclear:
        raise UnitRepairError(
            "splits UNCLEAR with no adjudication entry (ALL listed):\n  " + "\n  ".join(unclear)
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
    original = prices.filter(pl.col("source") == ORIGINAL_SOURCE)
    for sid, (before, _reason) in ADJUDICATED_BAR_EXCLUSIONS.items():
        cut = pl.lit(before).str.to_date()
        excluded = original.filter(
            (pl.col("security_id") == sid) & (pl.col("trade_date") < cut)
        ).height
        original = original.filter((pl.col("security_id") != sid) | (pl.col("trade_date") >= cut))
        logger.info(
            "bar exclusion %s: %d rows before %s dropped (adjudicated)", sid, excluded, before
        )
    original, spike_log = drop_single_bar_spikes(original)
    for line in spike_log:
        logger.info("spike filter: %s", line)
    dividends = pl.read_parquet(actions_dir / "eodhd_ftse100_dividends.parquet")
    for (sid, ex_date), _reason in ADJUDICATED_DIVIDEND_EXCLUSIONS.items():
        dividends = dividends.filter(
            (pl.col("security_id") != sid) | (pl.col("ex_date") != pl.lit(ex_date).str.to_date())
        )
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

    report_path = actions_dir / REPORT_FILE
    dividends_path = actions_dir / DIVIDENDS_FILE
    splits_path = actions_dir / SPLITS_FILE
    # Never overwrite a repaired dataset — but a pure EXTENSION (new securities added,
    # every pre-existing row byte-identical) keeps the same version: values for
    # existing consumers cannot change, which is the property the version protects.
    # Any difference in the pre-existing subset still refuses (bump the source).
    for path, new_frame in (
        (dividends_path, repaired_dividends),
        (splits_path, kept_splits),
    ):
        if path.exists():
            old = pl.read_parquet(path)

            def _comparable(frame: pl.DataFrame, columns: list[str]) -> pl.DataFrame:
                return frame.select([pl.col(c).cast(pl.Utf8).fill_null("<null>") for c in columns])

            merged = _comparable(old, old.columns).join(
                _comparable(new_frame, old.columns), on=old.columns, how="inner"
            )
            if merged.height < old.height:
                raise UnitRepairError(
                    f"{path}: {old.height - merged.height} pre-existing rows would "
                    "change — that is a re-adjudication, bump REPAIRED_SOURCE instead"
                )

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
