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
async def test_get_inverter_arrays_happy_path() -> None:
    respx.get(f"{BRIDGE_URL}/api/inverters/arrays").mock(
        return_value=httpx.Response(
            200,
            json={
                "window_start": 1745712000,
                "arrays": [
                    {
                        "name": "east",
                        "total_watts": 850.0,
                        "online_count": 2,
                        "total_count": 2,
                        "inverters": [
                            {
                                "serial_number": "121847012345",
                                "watts_output": 425.0,
                                "is_online": True,
                                "last_report_date": 1745712000,
                            },
                            {
                                "serial_number": "121847012346",
                                "watts_output": 425.0,
                                "is_online": True,
                                "last_report_date": 1745712000,
                            },
                        ],
                    },
                    {
                        "name": "west",
                        "total_watts": 0.0,
                        "online_count": 0,
                        "total_count": 1,
                        "inverters": [
                            {
                                "serial_number": "121847012347",
                                "watts_output": 0.0,
                                "is_online": False,
                                "last_report_date": 0,
                            }
                        ],
                    },
                ],
            },
        )
    )
    result = await make_client().get_inverter_arrays()
    assert result["window_start"] == 1745712000
    assert len(result["arrays"]) == 2
    assert result["arrays"][0]["name"] == "east"
    assert result["arrays"][0]["inverters"][0]["serial_number"] == "121847012345"
    assert result["arrays"][1]["inverters"][0]["is_online"] is False


@respx.mock
async def test_get_inverter_arrays_no_stored_data() -> None:
    """No windows recorded yet: bridge returns window_start=None and an empty arrays list."""
    respx.get(f"{BRIDGE_URL}/api/inverters/arrays").mock(
        return_value=httpx.Response(200, json={"window_start": None, "arrays": []})
    )
    result = await make_client().get_inverter_arrays()
    assert result["window_start"] is None
    assert result["arrays"] == []


@respx.mock
async def test_get_inverter_arrays_connect_error_raises_tool_error_with_url() -> None:
    respx.get(f"{BRIDGE_URL}/api/inverters/arrays").mock(side_effect=httpx.ConnectError("refused"))
    with pytest.raises(ToolError) as exc_info:
        await make_client().get_inverter_arrays()
    assert BRIDGE_URL in str(exc_info.value)
    assert "running?" in str(exc_info.value)


@respx.mock
async def test_get_inverter_arrays_500_raises_tool_error_with_message() -> None:
    respx.get(f"{BRIDGE_URL}/api/inverters/arrays").mock(
        return_value=httpx.Response(500, json={"error": "internal_error", "message": "db down"})
    )
    with pytest.raises(ToolError) as exc_info:
        await make_client().get_inverter_arrays()
    assert "500" in str(exc_info.value)
    assert "db down" in str(exc_info.value)


@respx.mock
async def test_get_inverter_arrays_malformed_json_raises_explicit_tool_error() -> None:
    respx.get(f"{BRIDGE_URL}/api/inverters/arrays").mock(
        return_value=httpx.Response(
            200, content=b"{not valid json", headers={"content-type": "application/json"}
        )
    )
    with pytest.raises(ToolError) as exc_info:
        await make_client().get_inverter_arrays()
    assert "malformed" in str(exc_info.value).lower()


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


# --- get_trueup_estimate -----------------------------------------------------


@respx.mock
async def test_get_trueup_estimate_happy_path() -> None:
    route = respx.get(f"{BRIDGE_URL}/api/trueup/estimate").mock(
        return_value=httpx.Response(
            200,
            json={
                "period_start": 1735718400,
                "period_end": 1755561600,
                "net_cost_usd": -40.5,
                "breakdown": {
                    "peak": {
                        "import_kwh": 40.0,
                        "export_kwh": 150.0,
                        "import_cost_usd": 20.0,
                        "export_credit_usd": 45.0,
                    },
                    "off_peak": {
                        "import_kwh": 60.0,
                        "export_kwh": 100.0,
                        "import_cost_usd": 18.0,
                        "export_credit_usd": 25.0,
                    },
                    "super_off_peak": {
                        "import_kwh": 20.0,
                        "export_kwh": 50.0,
                        "import_cost_usd": 4.0,
                        "export_credit_usd": 12.5,
                    },
                },
                "tou_schedule": {"id": 1, "rate_label": "EV2-A", "effective_date": "2026-01-01"},
                "computed_at": 1755720000,
                "excluded_window_count": 0,
            },
        )
    )
    start = datetime(2026, 1, 1, tzinfo=UTC)
    end = datetime(2026, 8, 18, tzinfo=UTC)
    result = await make_client().get_trueup_estimate(start, end)
    assert result["net_cost_usd"] == -40.5
    assert result["tou_schedule"]["rate_label"] == "EV2-A"
    request_params = route.calls[0].request.url.params
    assert request_params["start"] == "2026-01-01T00:00:00+00:00"
    assert request_params["end"] == "2026-08-18T00:00:00+00:00"


@respx.mock
async def test_get_trueup_estimate_connect_error_raises_tool_error_with_url() -> None:
    respx.get(f"{BRIDGE_URL}/api/trueup/estimate").mock(side_effect=httpx.ConnectError("refused"))
    with pytest.raises(ToolError) as exc_info:
        await make_client().get_trueup_estimate(
            datetime(2026, 1, 1, tzinfo=UTC), datetime(2026, 8, 18, tzinfo=UTC)
        )
    assert BRIDGE_URL in str(exc_info.value)
    assert "running?" in str(exc_info.value)


@respx.mock
async def test_get_trueup_estimate_no_schedule_raises_tool_error_with_message() -> None:
    """422 no_tou_schedule: no TOU rate schedule has been fetched yet."""
    respx.get(f"{BRIDGE_URL}/api/trueup/estimate").mock(
        return_value=httpx.Response(
            422,
            json={
                "error": "no_tou_schedule",
                "message": "no TOU rate schedule available; run POST /api/tou/refresh first",
            },
        )
    )
    with pytest.raises(ToolError) as exc_info:
        await make_client().get_trueup_estimate(
            datetime(2026, 1, 1, tzinfo=UTC), datetime(2026, 8, 18, tzinfo=UTC)
        )
    assert "422" in str(exc_info.value)
    assert "run POST /api/tou/refresh first" in str(exc_info.value)


@respx.mock
async def test_get_trueup_estimate_malformed_json_raises_explicit_tool_error() -> None:
    respx.get(f"{BRIDGE_URL}/api/trueup/estimate").mock(
        return_value=httpx.Response(
            200, content=b"{not valid json", headers={"content-type": "application/json"}
        )
    )
    with pytest.raises(ToolError) as exc_info:
        await make_client().get_trueup_estimate(
            datetime(2026, 1, 1, tzinfo=UTC), datetime(2026, 8, 18, tzinfo=UTC)
        )
    assert "malformed" in str(exc_info.value).lower()


# --- refresh_tou_schedule -----------------------------------------------------


@respx.mock
async def test_refresh_tou_schedule_happy_path() -> None:
    route = respx.post(f"{BRIDGE_URL}/api/tou/refresh").mock(
        return_value=httpx.Response(
            200,
            json={
                "schedule_id": 7,
                "rate_label": "EV2-A",
                "utility_name": "San Diego Gas & Electric",
                "effective_date": "2026-01-01",
                "fetched_at": 1755720000,
            },
        )
    )
    result = await make_client().refresh_tou_schedule()
    assert result["schedule_id"] == 7
    assert result["rate_label"] == "EV2-A"
    assert route.calls[0].request.method == "POST"


@respx.mock
async def test_refresh_tou_schedule_connect_error_raises_tool_error_with_url() -> None:
    respx.post(f"{BRIDGE_URL}/api/tou/refresh").mock(side_effect=httpx.ConnectError("refused"))
    with pytest.raises(ToolError) as exc_info:
        await make_client().refresh_tou_schedule()
    assert BRIDGE_URL in str(exc_info.value)
    assert "running?" in str(exc_info.value)


@respx.mock
async def test_refresh_tou_schedule_openei_unreachable_raises_tool_error_with_message() -> None:
    """502 upstream_unavailable: enphase-bridge could not reach OpenEI."""
    respx.post(f"{BRIDGE_URL}/api/tou/refresh").mock(
        return_value=httpx.Response(
            502,
            json={
                "error": "upstream_unavailable",
                "message": "error sending request for url (https://api.openei.org/...)",
            },
        )
    )
    with pytest.raises(ToolError) as exc_info:
        await make_client().refresh_tou_schedule()
    assert "502" in str(exc_info.value)
    assert "error sending request" in str(exc_info.value)


@respx.mock
async def test_refresh_tou_schedule_malformed_json_raises_explicit_tool_error() -> None:
    respx.post(f"{BRIDGE_URL}/api/tou/refresh").mock(
        return_value=httpx.Response(
            200, content=b"{not valid json", headers={"content-type": "application/json"}
        )
    )
    with pytest.raises(ToolError) as exc_info:
        await make_client().refresh_tou_schedule()
    assert "malformed" in str(exc_info.value).lower()
