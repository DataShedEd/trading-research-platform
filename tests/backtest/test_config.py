"""QNT-050: the config is the reproducibility artefact — hash-stable and fully frozen."""

from datetime import date
from decimal import Decimal

import pytest
from pydantic import ValidationError

from trp.backtest.config import BacktestConfig, RebalanceSchedule, Weighting


def make_config(**overrides: object) -> BacktestConfig:
    values: dict[str, object] = {
        "name": "momentum-ftse100",
        "start": date(2010, 1, 1),
        "end": date(2026, 1, 1),
        "universe": "FTSE100",
        "factor": "momentum_12_1",
        "factor_version": 1,
        "top_n": 20,
        "initial_cash": Decimal("10000000"),
    }
    values.update(overrides)
    return BacktestConfig(**values)  # type: ignore[arg-type]


def test_hash_is_deterministic() -> None:
    assert make_config().config_hash() == make_config().config_hash()


@pytest.mark.parametrize(
    "field, value",
    [
        ("name", "momentum-ftse100-b"),
        ("start", date(2011, 1, 1)),
        ("end", date(2025, 1, 1)),
        ("universe", "FTSE250"),
        ("factor", "momentum_6_1"),
        ("factor_version", 2),
        ("rebalance", RebalanceSchedule.QUARTERLY),
        ("weighting", Weighting.INVERSE_VOLATILITY),
        ("top_n", 10),
        ("initial_cash", Decimal("20000000")),
        ("commission_bps", Decimal("5")),
        ("commission_min", Decimal("0")),
        ("impact_coefficient_bps", Decimal("50")),
        ("spread_bps", Decimal("20")),
        ("stamp_duty_bps", Decimal("0")),
        ("benchmark", "FTSE100"),
        ("seed", 7),
        ("data_versions", {"prices": "v1"}),
    ],
)
def test_any_single_field_changes_the_hash(field: str, value: object) -> None:
    assert make_config(**{field: value}).config_hash() != make_config().config_hash()


def test_round_trip_preserves_hash() -> None:
    config = make_config(data_versions={"prices": "v3", "actions": "v2"})
    restored = BacktestConfig.model_validate_json(config.model_dump_json())
    assert restored == config
    assert restored.config_hash() == config.config_hash()


def test_end_must_follow_start() -> None:
    with pytest.raises(ValidationError, match="end must be after start"):
        make_config(end=date(2010, 1, 1))


def test_config_is_frozen() -> None:
    with pytest.raises(ValidationError):
        make_config().top_n = 5  # type: ignore[misc]


def test_name_is_filesystem_safe() -> None:
    with pytest.raises(ValidationError):
        make_config(name="Momentum Run #1")
