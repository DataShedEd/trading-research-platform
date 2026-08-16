from pathlib import Path

import pytest

from trp.config import Settings


def test_default_data_layout() -> None:
    settings = Settings(_env_file=None)
    assert settings.raw_dir == Path("data/raw")
    assert settings.canonical_dir == Path("data/canonical")
    assert settings.derived_dir == Path("data/derived")


def test_env_overrides(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("TRP_DATA_DIR", "/somewhere/else")
    monkeypatch.setenv("TRP_EODHD_API_KEY", "secret-key")
    settings = Settings(_env_file=None)
    assert settings.data_dir == Path("/somewhere/else")
    assert settings.eodhd_api_key is not None
    assert settings.eodhd_api_key.get_secret_value() == "secret-key"
    # Secrets must not appear in reprs or logs.
    assert "secret-key" not in repr(settings)


def test_ensure_data_dirs(tmp_path: Path) -> None:
    settings = Settings(_env_file=None, data_dir=tmp_path / "data")
    settings.ensure_data_dirs()
    assert (tmp_path / "data" / "raw").is_dir()
    assert (tmp_path / "data" / "canonical").is_dir()
    assert (tmp_path / "data" / "derived").is_dir()
