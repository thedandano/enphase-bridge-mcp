"""Unit tests for BridgeClient. All bridge calls are mocked via respx — never hits the network."""

from __future__ import annotations

from datetime import UTC, datetime

import httpx
import pytest
import respx
from mcp.server.mcpserver.exceptions import ToolError

from enphase_bridge_mcp.bridge_client import BridgeClient
from enphase_bridge_mcp.config import Settings

BRIDGE_URL = "http://localhost:8080"


def make_client(api_key: str | None = None) -> BridgeClient:
    return BridgeClient(Settings(bridge_url=BRIDGE_URL, bridge_api_key=api_key))


# --- happy paths -------------------------------------------------------------


@respx.mock
async def test_get_health_happy_path() -> None:
    respx.get(f"{BRIDGE_URL}/api/health").mock(
        return_value=httpx.Response(
            200,
            json={
                "status": "ok",
                "last_window_start": 1745712000,
                "token_expires_at": 1777248000,
                "uptime_seconds": 86400,
            },
        )
    )
    result = await make_client().get_health()
    assert result["status"] == "ok"
    assert result["uptime_seconds"] == 86400


@respx.mock
async def test_get_latest_window_happy_path() -> None:
    respx.get(f"{BRIDGE_URL}/api/energy/windows/latest").mock(
        return_value=httpx.Response(
            200,
            json={
                "window_start": 1745712000,
                "wh_produced": 423.5,
                "wh_consumed": 187.2,
                "wh_grid_import": 0.0,
                "wh_grid_export": 236.3,
                "is_complete": True,
            },
        )
    )
    result = await make_client().get_latest_window()
    assert result["window_start"] == 1745712000
    assert result["is_complete"] is True


@respx.mock
async def test_list_windows_single_page() -> None:
    respx.get(f"{BRIDGE_URL}/api/energy/windows").mock(
        return_value=httpx.Response(
            200,
            json={
                "windows": [
                    {
                        "window_start": 1745712000,
                        "wh_produced": 1.0,
                        "wh_consumed": 2.0,
                        "wh_grid_import": 0.0,
                        "wh_grid_export": 0.0,
                        "is_complete": True,
                    }
                ],
                "total": 1,
                "limit": 2880,
                "offset": 0,
            },
        )
    )
    start = datetime(2026, 4, 20, tzinfo=UTC)
    end = datetime(2026, 4, 21, tzinfo=UTC)
    result = await make_client().list_windows(start, end)
    assert len(result) == 1
    assert result[0]["window_start"] == 1745712000


@respx.mock
async def test_get_power_samples_happy_path() -> None:
    respx.get(f"{BRIDGE_URL}/api/power/samples").mock(
        return_value=httpx.Response(
            200,
            json={
                "samples": [
                    {
                        "sampled_at": 1745712000,
                        "production_w": 1200.0,
                        "consumption_w": 800.0,
                        "grid_w": -400.0,
                    }
                ],
                "total": 1,
                "limit": 500,
                "offset": 0,
            },
        )
    )
    result = await make_client().get_power_samples(1745712000, 1745715600, limit=500)
    assert len(result) == 1
    assert result[0]["grid_w"] == -400.0


# --- pagination ---------------------------------------------------------------


@respx.mock
async def test_list_windows_pages_across_multiple_requests(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("enphase_bridge_mcp.bridge_client._WINDOWS_PAGE_LIMIT", 2)

    def make_window(ts: int) -> dict[str, object]:
        return {
            "window_start": ts,
            "wh_produced": 1.0,
            "wh_consumed": 1.0,
            "wh_grid_import": 0.0,
            "wh_grid_export": 0.0,
            "is_complete": True,
        }

    route = respx.get(f"{BRIDGE_URL}/api/energy/windows")
    route.side_effect = [
        httpx.Response(
            200,
            json={
                "windows": [make_window(1), make_window(2)],
                "total": 3,
                "limit": 2,
                "offset": 0,
            },
        ),
        httpx.Response(
            200,
            json={"windows": [make_window(3)], "total": 3, "limit": 2, "offset": 2},
        ),
    ]

    start = datetime(2026, 4, 20, tzinfo=UTC)
    end = datetime(2026, 4, 21, tzinfo=UTC)
    result = await make_client().list_windows(start, end)

    assert [w["window_start"] for w in result] == [1, 2, 3]
    assert route.call_count == 2
    second_request_params = route.calls[1].request.url.params
    assert second_request_params["offset"] == "2"


@respx.mock
async def test_list_windows_stops_when_page_exactly_fills_limit(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A page returning exactly the page limit forces one more (empty) request."""
    monkeypatch.setattr("enphase_bridge_mcp.bridge_client._WINDOWS_PAGE_LIMIT", 2)

    def make_window(ts: int) -> dict[str, object]:
        return {
            "window_start": ts,
            "wh_produced": 1.0,
            "wh_consumed": 1.0,
            "wh_grid_import": 0.0,
            "wh_grid_export": 0.0,
            "is_complete": True,
        }

    route = respx.get(f"{BRIDGE_URL}/api/energy/windows")
    route.side_effect = [
        httpx.Response(
            200,
            json={"windows": [make_window(1), make_window(2)], "total": 2, "limit": 2, "offset": 0},
        ),
        httpx.Response(200, json={"windows": [], "total": 2, "limit": 2, "offset": 2}),
    ]

    start = datetime(2026, 4, 20, tzinfo=UTC)
    end = datetime(2026, 4, 21, tzinfo=UTC)
    result = await make_client().list_windows(start, end)

    assert [w["window_start"] for w in result] == [1, 2]
    assert route.call_count == 2


# --- network failures -----------------------------------------------------


@respx.mock
async def test_connect_error_raises_tool_error_with_url() -> None:
    respx.get(f"{BRIDGE_URL}/api/health").mock(side_effect=httpx.ConnectError("refused"))
    with pytest.raises(ToolError) as exc_info:
        await make_client().get_health()
    assert BRIDGE_URL in str(exc_info.value)
    assert "running?" in str(exc_info.value)


@respx.mock
async def test_timeout_raises_tool_error_with_url() -> None:
    respx.get(f"{BRIDGE_URL}/api/health").mock(side_effect=httpx.TimeoutException("timed out"))
    with pytest.raises(ToolError) as exc_info:
        await make_client().get_health()
    assert BRIDGE_URL in str(exc_info.value)
    assert "running?" in str(exc_info.value)


# --- HTTP error statuses ----------------------------------------------------


@respx.mock
async def test_401_with_json_body_raises_tool_error_with_message() -> None:
    respx.get(f"{BRIDGE_URL}/api/health").mock(
        return_value=httpx.Response(401, json={"error": "unauthorized", "message": "bad api key"})
    )
    with pytest.raises(ToolError) as exc_info:
        await make_client().get_health()
    assert "401" in str(exc_info.value)
    assert "bad api key" in str(exc_info.value)


@respx.mock
async def test_404_with_json_body_raises_tool_error_with_message() -> None:
    respx.get(f"{BRIDGE_URL}/api/energy/windows/latest").mock(
        return_value=httpx.Response(
            404, json={"error": "not_found", "message": "no windows recorded yet"}
        )
    )
    with pytest.raises(ToolError) as exc_info:
        await make_client().get_latest_window()
    assert "404" in str(exc_info.value)
    assert "no windows recorded yet" in str(exc_info.value)


@respx.mock
async def test_500_with_json_body_raises_tool_error_with_message() -> None:
    respx.get(f"{BRIDGE_URL}/api/health").mock(
        return_value=httpx.Response(500, json={"error": "internal_error", "message": "db down"})
    )
    with pytest.raises(ToolError) as exc_info:
        await make_client().get_health()
    assert "500" in str(exc_info.value)
    assert "db down" in str(exc_info.value)


@respx.mock
async def test_500_with_garbage_body_raises_tool_error_noting_unreadable() -> None:
    respx.get(f"{BRIDGE_URL}/api/health").mock(
        return_value=httpx.Response(
            500, content=b"\xff\xfenot json", headers={"content-type": "text/plain"}
        )
    )
    with pytest.raises(ToolError) as exc_info:
        await make_client().get_health()
    assert "500" in str(exc_info.value)
    assert "unreadable" in str(exc_info.value)


@respx.mock
async def test_200_with_malformed_json_raises_explicit_tool_error() -> None:
    respx.get(f"{BRIDGE_URL}/api/health").mock(
        return_value=httpx.Response(
            200, content=b"{not valid json", headers={"content-type": "application/json"}
        )
    )
    with pytest.raises(ToolError) as exc_info:
        await make_client().get_health()
    assert "malformed" in str(exc_info.value).lower()


# --- auth header -------------------------------------------------------------


@respx.mock
async def test_auth_header_present_when_api_key_configured() -> None:
    route = respx.get(f"{BRIDGE_URL}/api/health").mock(
        return_value=httpx.Response(200, json={"status": "ok"})
    )
    await make_client(api_key="secret-key").get_health()
    assert route.calls[0].request.headers["Authorization"] == "Bearer secret-key"


@respx.mock
async def test_auth_header_absent_when_no_api_key_configured() -> None:
    route = respx.get(f"{BRIDGE_URL}/api/health").mock(
        return_value=httpx.Response(200, json={"status": "ok"})
    )
    await make_client(api_key=None).get_health()
    assert "Authorization" not in route.calls[0].request.headers
