"""QNT-047: cross-sectional transforms on synthetic distributions."""

import polars as pl
import pytest

from trp.factors.definition import DefinitionError
from trp.factors.transforms import (
    cross_sectional,
    rank_percentile,
    registered_cross_sectional,
    sector_neutralise,
    winsorise,
    zscore,
    zscore_robust,
)


def frame(values: dict[str, float | None], statuses: dict[str, str] | None = None) -> pl.DataFrame:
    statuses = statuses or {}
    rows = [
        {
            "security_id": sid,
            "status": statuses.get(sid, "ok" if value is not None else "no_data"),
            "value": value,
            "warnings": [],
        }
        for sid, value in values.items()
    ]
    return pl.DataFrame(
        rows,
        schema={
            "security_id": pl.Utf8,
            "status": pl.Utf8,
            "value": pl.Float64,
            "warnings": pl.List(pl.Utf8),
        },
    )


def by_sid(result: pl.DataFrame) -> dict[str, dict]:  # type: ignore[type-arg]
    return {row["security_id"]: row for row in result.iter_rows(named=True)}


def test_transforms_are_registered_by_identifier() -> None:
    assert {
        "winsorise",
        "zscore",
        "zscore_robust",
        "rank_percentile",
        "sector_neutralise",
    } <= registered_cross_sectional()
    with pytest.raises(DefinitionError, match="unknown cross-sectional"):
        cross_sectional("median_madness")


def test_zscore_hand_case_and_determinism() -> None:
    data = frame({"a": 1.0, "b": 2.0, "c": 3.0, "d": 6.0})
    # mean 3, sample stdev sqrt((4+1+0+9)/3) = sqrt(14/3).
    result = by_sid(zscore(data, {}))
    stdev = (14 / 3) ** 0.5
    assert result["a"]["value"] == pytest.approx(-2 / stdev)
    assert result["d"]["value"] == pytest.approx(3 / stdev)
    shuffled = frame({"d": 6.0, "b": 2.0, "a": 1.0, "c": 3.0})
    assert by_sid(zscore(shuffled, {})) == {  # row order cannot matter
        sid: {**row} for sid, row in by_sid(zscore(data, {})).items()
    }


def test_robust_zscore_shrugs_at_an_outlier_where_standard_does_not() -> None:
    data = frame({"a": 1.0, "b": 2.0, "c": 3.0, "d": 4.0, "e": 1000.0})
    standard = by_sid(zscore(data, {}))
    robust = by_sid(zscore_robust(data, {}))
    # Under the standard z the outlier drags everyone's score far negative;
    # under median/MAD the inliers stay near zero and the outlier is enormous.
    assert abs(standard["b"]["value"]) < 0.6  # compressed by the inflated stdev
    assert abs(robust["b"]["value"]) < 0.8
    assert robust["e"]["value"] > 100
    assert standard["e"]["value"] < 2  # the outlier hides itself in its own stdev


def test_winsorise_hand_case_and_recorded_thresholds() -> None:
    values = {f"s{i:02d}": float(i) for i in range(1, 101)}  # 1..100
    parameters = {"lower_percentile": 5, "upper_percentile": 95}
    result = by_sid(winsorise(frame(values), parameters))
    # Interpolated percentiles over 1..100: p5 = 5.95, p95 = 95.05.
    assert result["s01"]["value"] == pytest.approx(5.95)
    assert result["s01"]["warnings"] == ["winsorised from 1"]
    assert result["s50"]["value"] == 50.0  # inside the bounds: untouched
    assert result["s50"]["warnings"] == []
    assert result["s99"]["value"] == pytest.approx(95.05)
    assert result["s100"]["value"] == pytest.approx(95.05)
    with pytest.raises(DefinitionError):  # thresholds are never defaulted silently
        winsorise(frame(values), {"lower_percentile": 40, "upper_percentile": 30})


def test_rank_percentile_tie_policies_exactly() -> None:
    data = frame({"a": 1.0, "b": 5.0, "c": 5.0, "d": 5.0, "e": 9.0})
    average = by_sid(rank_percentile(data, {"ties": "average"}))
    # Ranks: a=1, {b,c,d}=mean(2,3,4)=3, e=5; percentile = (rank - 0.5)/5.
    assert average["a"]["value"] == pytest.approx(0.1)
    assert average["b"]["value"] == average["c"]["value"] == pytest.approx(0.5)
    assert average["e"]["value"] == pytest.approx(0.9)
    minimum = by_sid(rank_percentile(data, {"ties": "min"}))
    assert minimum["b"]["value"] == pytest.approx((2 - 0.5) / 5)
    maximum = by_sid(rank_percentile(data, {"ties": "max"}))
    assert maximum["b"]["value"] == pytest.approx((4 - 0.5) / 5)
    with pytest.raises(DefinitionError, match="tie policy"):
        rank_percentile(data, {"ties": "coin_flip"})


def test_missing_values_stay_missing_and_stay_out_of_the_statistics() -> None:
    data = frame({"a": 1.0, "b": 3.0, "c": None})
    result = by_sid(zscore(data, {}))
    assert result["c"]["status"] == "no_data"
    assert result["c"]["value"] is None
    # Statistics over {1, 3} only: mean 2, stdev sqrt(2).
    assert result["a"]["value"] == pytest.approx(-1 / 2**0.5)


def test_degenerate_cross_sections_are_typed() -> None:
    constant = by_sid(zscore(frame({"a": 5.0, "b": 5.0, "c": 5.0}), {}))
    assert {row["status"] for row in constant.values()} == {"not_meaningful"}
    single = by_sid(zscore_robust(frame({"a": 5.0}), {}))
    assert single["a"]["status"] == "not_meaningful"
    empty = frame({"a": None, "b": None})
    assert zscore(empty, {}).equals(empty)  # all-missing passes through untouched
    ranked_constant = by_sid(rank_percentile(frame({"a": 2.0, "b": 2.0}), {}))
    assert {row["status"] for row in ranked_constant.values()} == {"not_meaningful"}


def test_sector_neutralise_demeans_within_groups_with_documented_fallback() -> None:
    data = frame({"a": 1.0, "b": 3.0, "c": 10.0, "d": 14.0, "e": 7.0, "f": 100.0, "g": 5.0})
    sectors = {"a": "X", "b": "X", "c": "X", "d": "X", "e": "Y", "f": "Y", "g": "Y"}
    result = by_sid(sector_neutralise(data, {"sectors": sectors, "min_group_size": 4}))
    assert result["a"]["value"] == pytest.approx(1.0 - 7.0)  # X mean = (1+3+10+14)/4 = 7
    assert result["d"]["value"] == pytest.approx(14.0 - 7.0)
    # Y has 3 < 4 members: passes through unneutralised, loudly.
    assert result["e"]["value"] == 7.0
    assert "not neutralised" in result["e"]["warnings"][0]
    orphan = by_sid(sector_neutralise(frame({"z": 4.0}), {"sectors": {}, "min_group_size": 2}))
    assert orphan["z"]["value"] == 4.0
    assert "no sector" in orphan["z"]["warnings"][0]
    with pytest.raises(DefinitionError, match="sectors mapping"):
        sector_neutralise(data, {})
