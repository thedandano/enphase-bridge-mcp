"""Unit tests for the milestone-3 MCP tool functions in cost_tools.py.

Tool functions are called directly (the `@server.tool()` decorator returns
the undecorated function). All bridge calls are mocked via respx — never
hits the network. Neither tool reads the server's clock (`computed_at`/
`fetched_at` come straight from the bridge's response body), so unlike
`test_analysis_tools.py` there's no clock to pin here.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

import httpx
import pytest
import respx
from mcp.server.mcpserver.exceptions import ToolError

from enphase_bridge_mcp.cost_tools import (
    ToUSchedule,
    TrueUpEstimate,
    get_trueup_estimate,
    refresh_tou_schedule,
)

BRIDGE_URL = "http://localhost:8080"


def make_estimate_response(
    net_cost_usd: float = -40.5, excluded_window_count: int = 0
) -> dict[str, Any]:
    return {
        "period_start": 1735718400,
        "period_end": 1755561600,
        "net_cost_usd": net_cost_usd,
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
        "excluded_window_count": excluded_window_count,
    }


def mock_estimate(**kwargs: Any) -> None:
    respx.get(f"{BRIDGE_URL}/api/trueup/estimate").mock(
        return_value=httpx.Response(200, json=make_estimate_response(**kwargs))
    )


# --- get_trueup_estimate --------------------------------------------------------


@respx.mock
async def test_get_trueup_estimate_happy_path_maps_response() -> None:
    route = respx.get(f"{BRIDGE_URL}/api/trueup/estimate").mock(
        return_value=httpx.Response(200, json=make_estimate_response())
    )

    result = await get_trueup_estimate(start_date="2026-01-01", end_date="2026-08-18")

    assert isinstance(result, TrueUpEstimate)
    assert result.start_date == "2026-01-01"
    assert result.end_date == "2026-08-18"
    assert result.net_cost_usd == -40.5
    assert result.peak.import_kwh == 40.0
    assert result.peak.export_credit_usd == 45.0
    assert result.off_peak.import_cost_usd == 18.0
    assert result.super_off_peak.export_kwh == 50.0
    assert result.tou_schedule.id == 1
    assert result.tou_schedule.rate_label == "EV2-A"
    assert result.tou_schedule.effective_date == "2026-01-01"
    assert result.computed_at == "2025-08-20T13:00:00-07:00"
    assert result.excluded_window_count == 0

    # The bridge's `end` param must be pre-compensated for its own fixed +24h
    # inclusivity adjustment: sending the Pacific exclusive-day boundary
    # straight through would silently include one extra day of data. Sending
    # exactly 24h before that boundary means the bridge's own +24h lands
    # precisely back on it.
    sent_start = route.calls[0].request.url.params["start"]
    sent_end = route.calls[0].request.url.params["end"]
    assert sent_start == datetime.fromisoformat("2026-01-01T08:00:00+00:00").isoformat()
    assert sent_end == datetime.fromisoformat("2026-08-18T07:00:00+00:00").isoformat()


@respx.mock
async def test_get_trueup_estimate_excluded_windows_surfaced() -> None:
    mock_estimate(excluded_window_count=12)
    result = await get_trueup_estimate(start_date="2026-01-01", end_date="2026-08-18")
    assert result.excluded_window_count == 12


@respx.mock
async def test_get_trueup_estimate_bad_start_date_raises_tool_error() -> None:
    with pytest.raises(ToolError, match="start_date"):
        await get_trueup_estimate(start_date="not-a-date", end_date="2026-08-18")


@respx.mock
async def test_get_trueup_estimate_bad_end_date_raises_tool_error() -> None:
    with pytest.raises(ToolError, match="end_date"):
        await get_trueup_estimate(start_date="2026-01-01", end_date="not-a-date")


@respx.mock
async def test_get_trueup_estimate_reversed_dates_raises_tool_error() -> None:
    with pytest.raises(ToolError, match="before"):
        await get_trueup_estimate(start_date="2026-08-18", end_date="2026-01-01")


@respx.mock
async def test_get_trueup_estimate_dst_spring_forward_single_day_raises_tool_error() -> None:
    """2026-03-08 is the Pacific spring-forward date (a 23h civil day); a
    same-day request's compensated `end` would land 1h before `start` on the
    wire, which the bridge rejects. Must fail fast with a clear message
    instead of forwarding an invalid request."""
    with pytest.raises(ToolError, match="spring-forward"):
        await get_trueup_estimate(start_date="2026-03-08", end_date="2026-03-08")


@respx.mock
async def test_get_trueup_estimate_dst_spring_forward_as_range_end_is_fine() -> None:
    """The DST day is only unrepresentable as a single-day request — as the
    end of a multi-day range it's business as usual."""
    mock_estimate()
    result = await get_trueup_estimate(start_date="2026-03-01", end_date="2026-03-08")
    assert result.end_date == "2026-03-08"


@respx.mock
async def test_get_trueup_estimate_range_too_large_raises_tool_error() -> None:
    with pytest.raises(ToolError, match="range too large"):
        await get_trueup_estimate(start_date="2024-01-01", end_date="2026-08-18")


@respx.mock
async def test_get_trueup_estimate_no_schedule_propagates_tool_error() -> None:
    respx.get(f"{BRIDGE_URL}/api/trueup/estimate").mock(
        return_value=httpx.Response(
            422,
            json={
                "error": "no_tou_schedule",
                "message": "no TOU rate schedule available; run POST /api/tou/refresh first",
            },
        )
    )
    with pytest.raises(ToolError, match="run POST /api/tou/refresh first"):
        await get_trueup_estimate(start_date="2026-01-01", end_date="2026-08-18")


@respx.mock
async def test_get_trueup_estimate_bridge_down_propagates_tool_error() -> None:
    respx.get(f"{BRIDGE_URL}/api/trueup/estimate").mock(side_effect=httpx.ConnectError("refused"))
    with pytest.raises(ToolError, match="Cannot reach enphase-bridge"):
        await get_trueup_estimate(start_date="2026-01-01", end_date="2026-08-18")


# --- refresh_tou_schedule --------------------------------------------------------


@respx.mock
async def test_refresh_tou_schedule_happy_path_maps_response() -> None:
    respx.post(f"{BRIDGE_URL}/api/tou/refresh").mock(
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

    result = await refresh_tou_schedule()

    assert isinstance(result, ToUSchedule)
    assert result.schedule_id == 7
    assert result.rate_label == "EV2-A"
    assert result.utility_name == "San Diego Gas & Electric"
    assert result.effective_date == "2026-01-01"
    assert result.fetched_at == "2025-08-20T13:00:00-07:00"


@respx.mock
async def test_refresh_tou_schedule_no_effective_date_maps_to_none() -> None:
    respx.post(f"{BRIDGE_URL}/api/tou/refresh").mock(
        return_value=httpx.Response(
            200,
            json={
                "schedule_id": 8,
                "rate_label": "EV2-A",
                "utility_name": "San Diego Gas & Electric",
                "effective_date": None,
                "fetched_at": 1755720000,
            },
        )
    )
    result = await refresh_tou_schedule()
    assert result.effective_date is None


@respx.mock
async def test_refresh_tou_schedule_openei_unreachable_propagates_tool_error() -> None:
    respx.post(f"{BRIDGE_URL}/api/tou/refresh").mock(
        return_value=httpx.Response(
            502,
            json={
                "error": "upstream_unavailable",
                "message": "error sending request for url (https://api.openei.org/...)",
            },
        )
    )
    with pytest.raises(ToolError, match="error sending request"):
        await refresh_tou_schedule()


@respx.mock
async def test_refresh_tou_schedule_bridge_down_propagates_tool_error() -> None:
    respx.post(f"{BRIDGE_URL}/api/tou/refresh").mock(side_effect=httpx.ConnectError("refused"))
    with pytest.raises(ToolError, match="Cannot reach enphase-bridge"):
        await refresh_tou_schedule()
