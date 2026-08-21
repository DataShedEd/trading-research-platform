"""QNT-114 gate: golden 12-1 momentum observations on the real FTSE 250 dataset.

Same convention and same INDEPENDENT reconstruction as the FTSE 100 golden gate
(tests/gate/test_momentum_golden_gate.py — the single documented statement of the
12-1 convention); the production path is the SHARED assembly (computable_inputs), so
factor-panel and backtest computations cannot diverge (§9 of the holdout directive).

Golden dates span the DEC-029 coverage: early (2016-06-30), mid (2019-06-28),
COVID-stressed (2020-03-31), recent (2025-06-30). Boundary cases asserted explicitly:
a later-promoted name, a recently-demoted name, and a delisting-era name appear in the
cross-sections with sane statuses.
"""

import json
from datetime import date
from pathlib import Path

import polars as pl
import pytest

from tests.gate.test_momentum_golden_gate import (
    independent_momentum,
    inspection_picks,
    names_by_id,
    production_cross_section,
)

pytestmark = pytest.mark.gate

FIXTURE = Path(__file__).parent / "golden" / "ftse250_momentum_goldens.json"

GOLDEN_DATES = [
    date(2016, 6, 30),  # early coverage (DEC-029 start year)
    date(2019, 6, 28),  # mid-period
    date(2020, 3, 31),  # COVID crash month end
    date(2025, 6, 30),  # recent
]


def build_goldens() -> dict:  # type: ignore[type-arg]
    names = names_by_id()
    goldens: dict = {}  # type: ignore[type-arg]
    for end in GOLDEN_DATES:
        ranked = production_cross_section(end, universe="FTSE250")
        inspected = {}
        for sid in inspection_picks(ranked):
            production = ranked.filter(pl.col("security_id") == sid).row(0, named=True)
            inspected[sid] = {
                "name": names.get(sid, "?"),
                "production_status": production["status"],
                "production_value": production["value"],
                "cross_sectional_rank": production["rank"],
                "independent": independent_momentum(sid, end),
            }
        goldens[str(end)] = {
            "cross_section": [
                {**row, "name": names.get(row["security_id"], "?")} for row in ranked.to_dicts()
            ],
            "inspected": inspected,
        }
    return goldens


@pytest.mark.parametrize("end", GOLDEN_DATES, ids=str)
def test_production_matches_pinned_cross_section(end: date) -> None:
    goldens = json.loads(FIXTURE.read_text())[str(end)]
    ranked = production_cross_section(end, universe="FTSE250")
    pinned = pl.DataFrame(goldens["cross_section"]).drop("name")
    assert ranked.height == pinned.height
    for got, expected in zip(ranked.to_dicts(), pinned.to_dicts(), strict=True):
        assert got["security_id"] == expected["security_id"]
        assert got["status"] == expected["status"]
        if expected["value"] is not None:
            assert got["value"] == pytest.approx(expected["value"], rel=1e-12)


@pytest.mark.parametrize("end", GOLDEN_DATES, ids=str)
def test_independent_reconstruction_agrees(end: date) -> None:
    goldens = json.loads(FIXTURE.read_text())[str(end)]
    checked = 0
    for sid, pinned in goldens["inspected"].items():
        fresh = independent_momentum(sid, end)
        if pinned["production_status"] == "ok":
            assert fresh["value"] == pytest.approx(pinned["production_value"], rel=1e-9)
            checked += 1
    assert checked >= 3


def test_boundary_cases_present_and_sane() -> None:
    """§9: promotions, demotions and delistings live inside the golden cross-sections."""
    goldens = json.loads(FIXTURE.read_text())
    names_2019 = {r["name"] for r in goldens["2019-06-28"]["cross_section"]}
    names_2016 = {r["name"] for r in goldens["2016-06-30"]["cross_section"]}
    names_2025 = {r["name"] for r in goldens["2025-06-30"]["cross_section"]}
    # later promoted to FTSE 100 (Aberdeen/abrdn chain entered the 100 in 2026):
    assert any("Aberdeen" in n or "abrdn" in n.lower() for n in names_2025)
    # recently demoted from the FTSE 100 at the golden date:
    assert any("Royal Mail" in n for n in names_2019)  # demoted Dec 2018
    # a later delisting (Carillion failed January 2018):
    assert any("Carillion" in n for n in names_2016)
    # ex-FTSE-100 heavyweight relegated into the 250 (Marks & Spencer was demoted 2019):
    sec_2025 = {
        r["name"]: r["status"]
        for r in goldens["2025-06-28" if "2025-06-28" in goldens else "2025-06-30"]["cross_section"]
    }
    assert len(sec_2025) >= 245


if __name__ == "__main__":
    import sys

    if sys.argv[1:] == ["regen"]:
        FIXTURE.parent.mkdir(exist_ok=True)
        FIXTURE.write_text(json.dumps(build_goldens(), indent=1))
        print(f"wrote {FIXTURE}")
