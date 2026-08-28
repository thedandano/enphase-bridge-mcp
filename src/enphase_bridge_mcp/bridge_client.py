"""Async HTTP client for the enphase-bridge Rust service.

Deliberately stateless: every method opens its own `httpx.AsyncClient` per HTTP
call rather than sharing a pooled client, matching the stateless-server design.
Every failure raises `ToolError` with a human-readable message — never a
silent None/empty/default.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

import httpx
from mcp.server.mcpserver.exceptions import ToolError

from .config import Settings

_WINDOWS_PAGE_LIMIT = 2880


class BridgeClient:
    """Thin async client for enphase-bridge, constructed from `Settings`."""

    def __init__(self, settings: Settings) -> None:
        self._settings = settings

    def _headers(self) -> dict[str, str]:
        if self._settings.bridge_api_key:
            return {"Authorization": f"Bearer {self._settings.bridge_api_key}"}
        return {}

    async def _get(self, path: str, params: dict[str, Any] | None = None) -> Any:
        async with httpx.AsyncClient(
            base_url=self._settings.bridge_url,
            timeout=10.0,
            headers=self._headers(),
        ) as client:
            try:
                response = await client.get(path, params=params)
            except (httpx.ConnectError, httpx.TimeoutException) as exc:
                raise ToolError(
                    f"Cannot reach enphase-bridge at {self._settings.bridge_url}: "
                    f"{exc}. Is the service running?"
                ) from exc

        if response.status_code >= 300:
            raise ToolError(self._describe_error(response))

        try:
            return response.json()
        except ValueError as exc:
            raise ToolError(
                f"enphase-bridge returned malformed JSON from {path} "
                f"(status {response.status_code}): {exc}"
            ) from exc

    @staticmethod
    def _describe_error(response: httpx.Response) -> str:
        try:
            body = response.json()
            message = body.get("message") if isinstance(body, dict) else None
            if message is None:
                message = str(body)
        except ValueError:
            message = "the response body was unreadable"
        return (
            f"enphase-bridge returned HTTP {response.status_code} for "
            f"{response.request.method} {response.request.url}: {message}"
        )

    async def get_health(self) -> dict[str, Any]:
        result = await self._get("/api/health")
        return dict(result)

    async def get_latest_window(self) -> dict[str, Any]:
        result = await self._get("/api/energy/windows/latest")
        return dict(result)

    async def list_windows(self, start_utc: datetime, end_utc: datetime) -> list[dict[str, Any]]:
        windows: list[dict[str, Any]] = []
        offset = 0
        while True:
            page = await self._get(
                "/api/energy/windows",
                params={
                    "start": start_utc.isoformat(),
                    "end": end_utc.isoformat(),
                    "limit": _WINDOWS_PAGE_LIMIT,
                    "offset": offset,
                },
            )
            batch = page["windows"]
            windows.extend(batch)
            if len(batch) < _WINDOWS_PAGE_LIMIT:
                break
            offset += _WINDOWS_PAGE_LIMIT
        return windows

    async def get_power_samples(
        self, start_epoch: int, end_epoch: int, limit: int = 500
    ) -> list[dict[str, Any]]:
        result = await self._get(
            "/api/power/samples",
            params={"start": start_epoch, "end": end_epoch, "limit": limit},
        )
        return list(result["samples"])

    async def get_inverter_arrays(self) -> dict[str, Any]:
        result = await self._get("/api/inverters/arrays")
        return dict(result)
