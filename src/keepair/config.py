"""Runtime settings, read from KEEPAIR_* environment variables."""

from __future__ import annotations

from pathlib import Path
from typing import Literal

from pydantic_settings import BaseSettings, SettingsConfigDict

REPO_ROOT = Path(__file__).resolve().parents[2]


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="KEEPAIR_")

    env: Literal["dev", "test", "demo", "prod"] = "dev"
    # Local development default only. Real deployments set KEEPAIR_DATABASE_URL.
    database_url: str = (
        "postgresql+psycopg://keepair:keepair@localhost:5432/keepair"  # pragma: allowlist secret
    )
    demo_mode: bool = True
    ui_dir: Path = REPO_ROOT / "ui"
    db_connect_timeout_s: int = 2
