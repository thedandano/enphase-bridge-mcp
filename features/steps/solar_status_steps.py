"""Step definitions for features/solar_status.feature.

Given steps build bridge fixtures (respx-mocked, via features/environment.py).
When steps call the MCP tool coroutines directly with `asyncio.run` — the
real wire protocol (tools/list, tools/call, MCP-level error shape) is already
exercised in tests/integration/test_http_transport.py, so these scenarios
focus on "does the owner's question get the right numbers back".
"""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime
from typing import Any

import httpx
from behave import given, then, when
from behave.model import Table
from behave.runner import Context

from enphase_bridge_mcp.formatting import PACIFIC, pacific_day_bounds
from enphase_bridge_mcp.server import CurrentStatus, DailySummary, DayComparison
from enphase_bridge_mcp.server import compare_days as compare_days_tool
from enphase_bridge_mcp.server import get_current_status as get_current_status_tool
from enphase_bridge_mcp.server import get_daily_summary as get_daily_summary_tool

BRIDGE_URL = "http://localhost:8080"
_WINDOW_SECONDS = 15 * 60


def _make_window(row: Any, window_start: int) -> dict[str, Any]:
    return {
        "window_start": window_start,
        "wh_produced": float(row["wh_produced"]),
        "wh_consumed": float(row["wh_consumed"]),
        "wh_grid_import": float(row.get("wh_grid_import", "0.0") or "0.0"),
        "wh_grid_export": float(row.get("wh_grid_export", "0.0") or "0.0"),
        "is_complete": (row.get("is_complete", "true") or "true").strip().lower() == "true",
    }


def _register_day_windows(context: Context, date_spec: str, table: Table) -> None:
    start_utc, _end_utc = pacific_day_bounds(date_spec, now=context.fixed_now)
    base = int(start_utc.timestamp())
    windows = [_make_window(row, base + i * _WINDOW_SECONDS) for i, row in enumerate(table)]
    context.day_windows_by_start[start_utc.isoformat()] = windows


# --- Given --------------------------------------------------------


@given("today is {date} (Pacific)")
def step_today_is(context: Context, date: str) -> None:
    year, month, day = (int(part) for part in date.split("-"))
    # A pinned mid-day instant, so it's unambiguously "today" in Pacific.
    context.fixed_now = datetime(year, month, day, 12, 0, 0, tzinfo=PACIFIC).astimezone(UTC)


@given("enphase-bridge is reachable")
def step_bridge_is_reachable(context: Context) -> None:
    pass  # documents scenario intent; per-endpoint mocks are registered by the steps below


@given(
    "the bridge's latest energy window started {minutes_ago:d} minutes ago "
    "producing {wh_produced:f} Wh and consuming {wh_consumed:f} Wh"
)
def step_latest_window(
    context: Context, minutes_ago: int, wh_produced: float, wh_consumed: float
) -> None:
    window_start = int(context.fixed_now.timestamp()) - minutes_ago * 60
    window = _make_window(
        {"wh_produced": str(wh_produced), "wh_consumed": str(wh_consumed)}, window_start
    )
    context.respx_mock.get(f"{BRIDGE_URL}/api/energy/windows/latest").mock(
        return_value=httpx.Response(200, json=window)
    )


@given(
    "the bridge's most recent power sample reads {production_w:f} W production, "
    "{consumption_w:f} W consumption, {grid_w:f} W grid"
)
def step_power_sample(
    context: Context, production_w: float, consumption_w: float, grid_w: float
) -> None:
    sampled_at = int(context.fixed_now.timestamp()) - 60
    context.respx_mock.get(f"{BRIDGE_URL}/api/power/samples").mock(
        return_value=httpx.Response(
            200,
            json={
                "samples": [
                    {
                        "sampled_at": sampled_at,
                        "production_w": production_w,
                        "consumption_w": consumption_w,
                        "grid_w": grid_w,
                    }
                ],
                "total": 1,
                "limit": 50,
                "offset": 0,
            },
        )
    )


@given("the bridge has been up for {uptime_seconds:d} seconds")
def step_bridge_uptime(context: Context, uptime_seconds: int) -> None:
    context.respx_mock.get(f"{BRIDGE_URL}/api/health").mock(
        return_value=httpx.Response(
            200,
            json={
                "status": "ok",
                "last_window_start": int(context.fixed_now.timestamp()),
                "token_expires_at": 0,
                "uptime_seconds": uptime_seconds,
            },
        )
    )


@given("today's energy windows (Pacific) are:")
def step_today_windows(context: Context) -> None:
    _register_day_windows(context, "today", context.table)


@given("yesterday's energy windows (Pacific) are:")
def step_yesterday_windows(context: Context) -> None:
    _register_day_windows(context, "yesterday", context.table)


# --- When --------------------------------------------------------


@when("I ask for the current solar status")
def step_ask_current_status(context: Context) -> None:
    context.result = asyncio.run(get_current_status_tool())


@when("I ask for yesterday's daily summary")
def step_ask_yesterday_summary(context: Context) -> None:
    context.result = asyncio.run(get_daily_summary_tool(date="yesterday"))


@when("I compare today to yesterday")
def step_compare_today_yesterday(context: Context) -> None:
    context.result = asyncio.run(compare_days_tool(date_a="today", date_b="yesterday"))


# --- Then: current status --------------------------------------------------------


@then("the system is reported online")
def step_then_online(context: Context) -> None:
    assert isinstance(context.result, CurrentStatus)
    assert context.result.is_online is True


@then("the instantaneous production is {value:f} W")
def step_then_instantaneous_production(context: Context, value: float) -> None:
    assert isinstance(context.result, CurrentStatus)
    assert context.result.production_w == value


@then("today's produced energy is {value:f} kWh")
def step_then_today_produced(context: Context, value: float) -> None:
    assert isinstance(context.result, CurrentStatus)
    assert context.result.today_produced_kwh == value


@then("today's consumed energy is {value:f} kWh")
def step_then_today_consumed(context: Context, value: float) -> None:
    assert isinstance(context.result, CurrentStatus)
    assert context.result.today_consumed_kwh == value


# --- Then: daily summary --------------------------------------------------------


@then("the produced energy is {value:f} kWh")
def step_then_produced(context: Context, value: float) -> None:
    assert isinstance(context.result, DailySummary)
    assert context.result.produced_kwh == value


@then("the consumed energy is {value:f} kWh")
def step_then_consumed(context: Context, value: float) -> None:
    assert isinstance(context.result, DailySummary)
    assert context.result.consumed_kwh == value


@then("the net energy is {value:f} kWh")
def step_then_net(context: Context, value: float) -> None:
    assert isinstance(context.result, DailySummary)
    assert context.result.net_kwh == value


@then("the data completeness is {value:f} percent")
def step_then_completeness(context: Context, value: float) -> None:
    assert isinstance(context.result, DailySummary)
    assert context.result.data_completeness_pct == value


# --- Then: day comparison --------------------------------------------------------


@then("day A's produced energy is {value:f} kWh")
def step_then_day_a_produced(context: Context, value: float) -> None:
    assert isinstance(context.result, DayComparison)
    assert context.result.day_a.produced_kwh == value


@then("day B's produced energy is {value:f} kWh")
def step_then_day_b_produced(context: Context, value: float) -> None:
    assert isinstance(context.result, DayComparison)
    assert context.result.day_b.produced_kwh == value


@then("the produced energy difference is {value:f} kWh")
def step_then_produced_diff(context: Context, value: float) -> None:
    assert isinstance(context.result, DayComparison)
    assert context.result.produced_kwh_diff == value


@then("the produced energy percent difference is {value:f} percent")
def step_then_produced_pct_diff(context: Context, value: float) -> None:
    assert isinstance(context.result, DayComparison)
    assert context.result.produced_pct_diff == value
