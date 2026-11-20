"""Runtime settings, read from KEEPAIR_* environment variables."""

from __future__ import annotations

import tempfile
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
    provider_timeout_s: float = 120.0
    gateway_url: str = "http://localhost:8080"
    mock_provider_url: str = "http://localhost:8090"
    fixtures_dir: Path = REPO_ROOT / "tests" / "fixtures" / "providers"
    # Fail-open spool. The key is 32 bytes, base64. Required in production.
    spool_dir: Path = Path(tempfile.gettempdir()) / "keepair-spool"
    spool_key: str | None = None
