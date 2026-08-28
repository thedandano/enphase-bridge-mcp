"""Runtime settings for the enphase-bridge-mcp server, loaded from env vars / .env."""

from __future__ import annotations

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="ENPHASE_MCP_", env_file=".env", extra="ignore")

    bridge_url: str = "http://localhost:8080"
    bridge_api_key: str | None = None
    host: str = "127.0.0.1"
    port: int = 8000
