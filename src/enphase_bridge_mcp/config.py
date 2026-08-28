"""Runtime settings for the enphase-bridge-mcp server, loaded from env vars / .env."""

from __future__ import annotations

from typing import Annotated, Any

from pydantic import field_validator
from pydantic_settings import BaseSettings, NoDecode, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="ENPHASE_MCP_", env_file=".env", extra="ignore")

    bridge_url: str = "http://localhost:8080"
    bridge_api_key: str | None = None
    host: str = "127.0.0.1"
    port: int = 8000
    allowed_hosts: Annotated[list[str], NoDecode] = []
    """Extra `Host` header values (e.g. `192.168.1.50:8000`) the streamable-HTTP
    transport should accept in addition to loopback, parsed from a
    comma-separated `ENPHASE_MCP_ALLOWED_HOSTS`. Empty by default, which keeps
    the MCP SDK's own defaults (loopback-only when bound to a loopback host,
    unrestricted otherwise) — setting this does NOT add a wildcard fallback,
    it only ever allows exactly the hosts listed."""

    @field_validator("allowed_hosts", mode="before")
    @classmethod
    def _split_allowed_hosts(cls, value: Any) -> Any:  # noqa: ANN401
        if isinstance(value, str):
            return [host.strip() for host in value.split(",") if host.strip()]
        return value
