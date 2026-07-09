from __future__ import annotations

from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Env-backed config for the remote HTTP service. ``api_key`` has no default —
    a missing ``QAI_API_KEY`` must fail startup loud, never fall back to "no auth"."""

    model_config = SettingsConfigDict(env_prefix="QAI_")

    api_key: str
    host: str = "0.0.0.0"
    port: int = 8000
    session_db_path: Path = Path("qai-reports") / ".pipeline_sessions.sqlite3"
