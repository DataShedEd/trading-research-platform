"""Application configuration.

Settings load from the environment (prefix ``TRP_``) and an optional ``.env`` file at the
repository root. Data-layer paths default to ``data/`` relative to the current working
directory, which is expected to be the repository root; set ``TRP_DATA_DIR`` to relocate.
"""

from pathlib import Path

from pydantic import SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="TRP_",
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    data_dir: Path = Path("data")

    # Provider credentials; absence means the provider is unavailable, never an error at import.
    eodhd_api_key: SecretStr | None = None
    fmp_api_key: SecretStr | None = None
    tiingo_api_key: SecretStr | None = None

    log_level: str = "INFO"

    @property
    def raw_dir(self) -> Path:
        return self.data_dir / "raw"

    @property
    def canonical_dir(self) -> Path:
        return self.data_dir / "canonical"

    @property
    def derived_dir(self) -> Path:
        return self.data_dir / "derived"

    def ensure_data_dirs(self) -> None:
        for path in (self.raw_dir, self.canonical_dir, self.derived_dir):
            path.mkdir(parents=True, exist_ok=True)


def load_settings() -> Settings:
    """Construct settings from the environment. Call at application entry points, not import."""
    return Settings()
