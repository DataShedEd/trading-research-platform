"""The factor compute surface: resolve inputs, apply the transform, tag every value.

``as_of`` is an argument of the surface, not a detail of individual factors — the
context hands each transform inputs plus the knowledge instant, and every input read
happens through point-in-time machinery (the returns engine takes ``as_of``; fundamental
reads go through the QNT-025 query). This is what makes QNT-049's leakage suite possible.

Every persisted value carries the definition name, definition version, the ``as_of`` it
was computed at, and the versions of its input datasets; the writer refuses frames
missing any tag. Two versions of a factor coexist in the store
(``data/derived/factors/name=<n>/version=<v>/``).
"""

from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from datetime import date, datetime
from itertools import pairwise
from pathlib import Path

import polars as pl

from trp.domain.corporate_actions import CorporateAction
from trp.domain.identifiers import SecurityId
from trp.domain.prices import DailyBar
from trp.factors.definition import DefinitionError, FactorDefinition
from trp.factors.returns import ReturnBasis, ReturnsEngine, ReturnStatus, WindowSpec


@dataclass(frozen=True)
class ComputeContext:
    """Inputs a transform may draw on, plus the knowledge instant governing them all."""

    security_ids: Sequence[SecurityId]
    end: date
    as_of: datetime
    bars: Sequence[DailyBar] = ()
    actions: Sequence[CorporateAction] = ()
    input_versions: dict[str, str] = field(default_factory=dict)
    mic: str = "XLON"


TransformFn = Callable[[ComputeContext, dict[str, object]], pl.DataFrame]

_TRANSFORMS: dict[str, TransformFn] = {}


def register_transform(name: str) -> Callable[[TransformFn], TransformFn]:
    def decorator(fn: TransformFn) -> TransformFn:
        if name in _TRANSFORMS:
            raise DefinitionError(f"transform {name!r} already registered")
        _TRANSFORMS[name] = fn
        return fn

    return decorator


def registered_transforms() -> frozenset[str]:
    return frozenset(_TRANSFORMS)


@register_transform("window_total_return")
def _window_total_return(context: ComputeContext, parameters: dict[str, object]) -> pl.DataFrame:
    """The momentum primitive: a windowed return per security via the returns library."""
    window = WindowSpec(
        months=int(parameters["months"]),  # type: ignore[call-overload]
        skip_months=int(parameters.get("skip_months", 0)),  # type: ignore[call-overload]
    )
    basis = ReturnBasis(str(parameters.get("basis", "total")))
    engine = ReturnsEngine(
        list(context.bars), list(context.actions), as_of=context.as_of, mic=context.mic
    )
    return engine.cross_section(context.security_ids, context.end, window, basis).select(
        "security_id",
        "status",
        pl.col("value"),
        pl.col("warnings"),
    )


@register_transform("window_return_over_volatility")
def _window_return_over_volatility(
    context: ComputeContext, parameters: dict[str, object]
) -> pl.DataFrame:
    """Volatility-adjusted momentum: the windowed return divided by realised volatility
    of DAILY returns from the same adjusted series over the same window, annualised as
    stdev x sqrt(252) (the documented convention). Near-zero volatility (< 1e-6
    annualised, e.g. a flat or suspended series) yields the typed insufficient-data
    status rather than an exploding ratio."""
    window = WindowSpec(
        months=int(parameters["months"]),  # type: ignore[call-overload]
        skip_months=int(parameters.get("skip_months", 0)),  # type: ignore[call-overload]
    )
    basis = ReturnBasis(str(parameters.get("basis", "total")))
    engine = ReturnsEngine(
        list(context.bars), list(context.actions), as_of=context.as_of, mic=context.mic
    )
    rows = []
    for security_id in context.security_ids:
        result = engine.window_return(security_id, context.end, window, basis)
        value: float | None = None
        status = result.status.value
        warnings = "; ".join(result.warnings)
        if result.status is ReturnStatus.OK and result.value is not None:
            series = [
                v
                for d, v in engine.adjusted_series(security_id, basis)
                if result.start_bar is not None
                and result.end_bar is not None
                and result.start_bar <= d <= result.end_bar
            ]
            daily = [b / a - 1.0 for a, b in pairwise(series) if a > 0]
            volatility = _annualised_stdev(daily)
            if volatility is None or volatility < 1e-6:
                status = ReturnStatus.INSUFFICIENT_DATA.value
                warnings = (warnings + "; " if warnings else "") + "near-zero volatility"
            else:
                value = result.value / volatility
        rows.append(
            {
                "security_id": security_id,
                "status": status,
                "value": value,
                "warnings": warnings,
            }
        )
    return pl.DataFrame(
        rows,
        schema={
            "security_id": pl.Utf8,
            "status": pl.Utf8,
            "value": pl.Float64,
            "warnings": pl.Utf8,
        },
    )


def _annualised_stdev(daily_returns: list[float]) -> float | None:
    n = len(daily_returns)
    if n < 20:  # too few observations for a meaningful volatility
        return None
    mean = sum(daily_returns) / n
    variance = sum((r - mean) ** 2 for r in daily_returns) / (n - 1)
    return float((variance**0.5) * (252.0**0.5))


def compute_factor(definition: FactorDefinition, context: ComputeContext) -> pl.DataFrame:
    transform = _TRANSFORMS.get(definition.transform)
    if transform is None:
        raise DefinitionError(f"transform {definition.transform!r} is not registered")
    values = transform(context, dict(definition.parameters))
    return values.with_columns(
        pl.lit(definition.name).alias("factor"),
        pl.lit(definition.version).alias("factor_version"),
        pl.lit(context.end).alias("end"),
        pl.lit(context.as_of).alias("as_of"),
        pl.lit(";".join(f"{k}={v}" for k, v in sorted(context.input_versions.items()))).alias(
            "input_versions"
        ),
    )


def write_factor_values(frame: pl.DataFrame, root: Path) -> Path:
    """Persist one computation. Refuses untagged frames and never overwrites."""
    required = {"factor", "factor_version", "end", "as_of", "input_versions", "security_id"}
    missing = required - set(frame.columns)
    if missing:
        raise DefinitionError(
            f"refusing to write untagged factor values: missing {sorted(missing)}"
        )
    if frame.select(pl.col("factor").n_unique()).item() != 1:
        raise DefinitionError("one factor per write")
    name = frame["factor"][0]
    version = int(frame["factor_version"][0])
    end = frame["end"][0]
    directory = root / f"name={name}" / f"version={version}"
    directory.mkdir(parents=True, exist_ok=True)
    target = directory / f"end={end.isoformat()}.parquet"
    if target.exists():
        raise DefinitionError(f"{target} exists; factor values are never overwritten")
    frame.write_parquet(target)
    return target
