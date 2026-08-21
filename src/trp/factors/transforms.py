"""Cross-sectional transforms (QNT-047): winsorise, standardise, rank, neutralise.

These operate per date ACROSS a cross-section frame (security_id, status, value,
warnings) — the QNT-042 transform output shape. The universe is part of the result: a
z-score is relative to whoever else is in the frame, so callers pass the cross-section
they mean, never "whatever rows were around".

Policies, uniform across every transform here:
- Only ``status == "ok"`` rows are touched; every other row passes through unchanged.
  Missingness is never imputed — not to zero, not to the mean — it propagates for the
  composite's missing policy (QNT-048) to decide.
- Deterministic and row-order independent: output order is input order, values depend
  only on the multiset of inputs (ties in ranking follow the configured policy exactly).
- Degenerate cross-sections are typed: a constant cross-section has zero dispersion and
  no ranking information (``not_meaningful``), a single-member one has no distribution
  (``not_meaningful``), an all-missing one passes through.

Each transform is registered by identifier in the cross-sectional registry so composite
configurations can name it; parameters live in the composite definition, versioned —
a winsorisation threshold changed after seeing results is a new version by construction.
"""

import math
from collections.abc import Callable, Mapping

import polars as pl

from trp.factors.definition import DefinitionError

CrossSectionalFn = Callable[[pl.DataFrame, Mapping[str, object]], pl.DataFrame]

_CROSS_SECTIONAL: dict[str, CrossSectionalFn] = {}

NOT_MEANINGFUL = "not_meaningful"


def register_cross_sectional(name: str) -> Callable[[CrossSectionalFn], CrossSectionalFn]:
    def decorator(fn: CrossSectionalFn) -> CrossSectionalFn:
        if name in _CROSS_SECTIONAL:
            raise DefinitionError(f"cross-sectional transform {name!r} already registered")
        _CROSS_SECTIONAL[name] = fn
        return fn

    return decorator


def cross_sectional(name: str) -> CrossSectionalFn:
    fn = _CROSS_SECTIONAL.get(name)
    if fn is None:
        raise DefinitionError(
            f"unknown cross-sectional transform {name!r}; known: {sorted(_CROSS_SECTIONAL)}"
        )
    return fn


def registered_cross_sectional() -> frozenset[str]:
    return frozenset(_CROSS_SECTIONAL)


def _ok_values(frame: pl.DataFrame) -> list[tuple[str, float]]:
    return [
        (row["security_id"], float(row["value"]))
        for row in frame.iter_rows(named=True)
        if row["status"] == "ok" and row["value"] is not None
    ]


def _apply(
    frame: pl.DataFrame, mapped: dict[str, tuple[str, float | None, list[str]]]
) -> pl.DataFrame:
    """Rebuild the frame in input order, replacing only the rows present in ``mapped``."""
    rows = []
    for row in frame.iter_rows(named=True):
        replacement = mapped.get(row["security_id"])
        if replacement is None:
            rows.append({**row, "warnings": [str(w) for w in row["warnings"] or []]})
        else:
            status, value, extra = replacement
            rows.append(
                {
                    **row,
                    "status": status,
                    "value": value,
                    "warnings": [str(w) for w in row["warnings"] or []] + extra,
                }
            )
    # An all-empty warnings column infers as List(Null) upstream; pin it to List(Utf8)
    # so transformed rows can append their notes.
    schema = dict(frame.schema.items())
    schema["warnings"] = pl.List(pl.Utf8)
    return pl.DataFrame(rows, schema=schema)


def _degenerate(
    frame: pl.DataFrame, values: list[tuple[str, float]], label: str
) -> pl.DataFrame | None:
    if not values:
        return frame  # all-missing: nothing to standardise, nothing to invent
    if len(values) == 1:
        return _apply(
            frame,
            {values[0][0]: (NOT_MEANINGFUL, None, [f"single-member cross-section for {label}"])},
        )
    spread = max(v for _s, v in values) - min(v for _s, v in values)
    if spread == 0:
        return _apply(
            frame,
            {
                sid: (NOT_MEANINGFUL, None, [f"constant cross-section for {label}"])
                for sid, _v in values
            },
        )
    return None


@register_cross_sectional("winsorise")
def winsorise(frame: pl.DataFrame, parameters: Mapping[str, object]) -> pl.DataFrame:
    """Clamp to the configured percentiles (midpoint-interpolated). Thresholds come from
    the caller's configuration — there is deliberately no default."""
    lower_pct = float(parameters["lower_percentile"])  # type: ignore[arg-type]
    upper_pct = float(parameters["upper_percentile"])  # type: ignore[arg-type]
    if not 0 <= lower_pct < upper_pct <= 100:
        raise DefinitionError(f"bad winsorisation percentiles [{lower_pct}, {upper_pct}]")
    values = _ok_values(frame)
    if len(values) < 2:
        return frame
    ordered = sorted(v for _s, v in values)
    low = _percentile(ordered, lower_pct)
    high = _percentile(ordered, upper_pct)
    mapped: dict[str, tuple[str, float | None, list[str]]] = {}
    for sid, v in values:
        clamped = min(max(v, low), high)
        if clamped != v:
            mapped[sid] = ("ok", clamped, [f"winsorised from {v:.6g}"])
    return _apply(frame, mapped)


def _percentile(ordered: list[float], pct: float) -> float:
    position = (len(ordered) - 1) * pct / 100
    lower_index = math.floor(position)
    upper_index = math.ceil(position)
    weight = position - lower_index
    return ordered[lower_index] * (1 - weight) + ordered[upper_index] * weight


@register_cross_sectional("zscore")
def zscore(frame: pl.DataFrame, parameters: Mapping[str, object]) -> pl.DataFrame:
    """(v - mean) / sample stdev over the ok rows."""
    values = _ok_values(frame)
    degenerate = _degenerate(frame, values, "zscore")
    if degenerate is not None:
        return degenerate
    n = len(values)
    mean = sum(v for _s, v in values) / n
    stdev = math.sqrt(sum((v - mean) ** 2 for _s, v in values) / (n - 1))
    return _apply(frame, {sid: ("ok", (v - mean) / stdev, []) for sid, v in values})


@register_cross_sectional("zscore_robust")
def zscore_robust(frame: pl.DataFrame, parameters: Mapping[str, object]) -> pl.DataFrame:
    """(v - median) / (1.4826 x MAD): outliers move themselves, not everyone's score.
    Zero MAD with nonzero range (a heavy central spike) is degenerate for the spiked
    values' scale — refused as not_meaningful for the whole cross-section."""
    values = _ok_values(frame)
    degenerate = _degenerate(frame, values, "zscore_robust")
    if degenerate is not None:
        return degenerate
    ordered = sorted(v for _s, v in values)
    median = _percentile(ordered, 50)
    mad = _percentile(sorted(abs(v - median) for v in ordered), 50)
    if mad == 0:
        return _apply(
            frame,
            {sid: (NOT_MEANINGFUL, None, ["zero MAD: no robust scale"]) for sid, _v in values},
        )
    scale = 1.4826 * mad
    return _apply(frame, {sid: ("ok", (v - median) / scale, []) for sid, v in values})


@register_cross_sectional("rank_percentile")
def rank_percentile(frame: pl.DataFrame, parameters: Mapping[str, object]) -> pl.DataFrame:
    """Ascending percentile in (0, 1): (rank - 0.5) / n, ties by the configured policy —
    ``average`` (default: equal values share the mean of their ranks), ``min`` or ``max``."""
    ties = str(parameters.get("ties", "average"))
    if ties not in {"average", "min", "max"}:
        raise DefinitionError(f"unknown tie policy {ties!r}")
    values = _ok_values(frame)
    degenerate = _degenerate(frame, values, "rank_percentile")
    if degenerate is not None:
        return degenerate
    n = len(values)
    ordered = sorted(values, key=lambda pair: (pair[1], pair[0]))
    ranks: dict[str, float] = {}
    index = 0
    while index < n:
        j = index
        while j < n and ordered[j][1] == ordered[index][1]:
            j += 1
        group = list(range(index + 1, j + 1))  # 1-based ranks of the tied block
        rank = {"average": sum(group) / len(group), "min": group[0], "max": group[-1]}[ties]
        for k in range(index, j):
            ranks[ordered[k][0]] = rank
        index = j
    return _apply(frame, {sid: ("ok", (rank - 0.5) / n, []) for sid, rank in ranks.items()})


@register_cross_sectional("sector_neutralise")
def sector_neutralise(frame: pl.DataFrame, parameters: Mapping[str, object]) -> pl.DataFrame:
    """Demean within sector groups. ``sectors`` maps security_id -> sector AS KNOWN AT the
    computation date (the caller owns that point-in-time lookup — no sector reference
    data ships with the platform yet). A group below ``min_group_size`` (default 4), and
    any security without a sector, passes through UNNEUTRALISED with a warning — visible,
    never silently dropped or silently global-demeaned."""
    sectors_raw = parameters.get("sectors")
    if not isinstance(sectors_raw, Mapping):
        raise DefinitionError("sector_neutralise requires a sectors mapping")
    sectors = {str(k): str(v) for k, v in sectors_raw.items()}
    min_group = int(parameters.get("min_group_size", 4))  # type: ignore[call-overload]
    values = _ok_values(frame)
    by_sector: dict[str, list[tuple[str, float]]] = {}
    for sid, v in values:
        sector = sectors.get(sid)
        if sector is not None:
            by_sector.setdefault(sector, []).append((sid, v))
    mapped: dict[str, tuple[str, float | None, list[str]]] = {}
    for sid, v in values:
        sector = sectors.get(sid)
        if sector is None:
            mapped[sid] = ("ok", v, ["no sector: not neutralised"])
            continue
        group = by_sector[sector]
        if len(group) < min_group:
            note = f"sector {sector} has {len(group)} < {min_group}: not neutralised"
            mapped[sid] = ("ok", v, [note])
            continue
        group_mean = sum(gv for _g, gv in group) / len(group)
        mapped[sid] = ("ok", v - group_mean, [])
    return _apply(frame, mapped)
