"""Step definitions for features/analysis.feature.

Given steps build bridge fixtures (respx-mocked, via features/environment.py).
When steps call the milestone-2 MCP tool coroutines directly with
`asyncio.run`. Mirrors the style of `solar_status_steps.py`.
"""

from __future__ import annotations

import asyncio
from typing import Any

import httpx
from behave import given, then, when
from behave.runner import Context

from enphase_bridge_mcp.analysis_tools import InverterHealth, PeriodComparison
from enphase_bridge_mcp.analysis_tools import compare_periods as compare_periods_tool
from enphase_bridge_mcp.analysis_tools import get_inverter_health as get_inverter_health_tool
from enphase_bridge_mcp.formatting import pacific_day_bounds

BRIDGE_URL = "http://localhost:8080"
_WINDOW_SECONDS = 15 * 60


def _make_window(row: Any) -> dict[str, Any]:
    return {
        "wh_produced": float(row["wh_produced"]),
        "wh_consumed": float(row["wh_consumed"]),
        "wh_grid_import": float(row.get("wh_grid_import", "0.0") or "0.0"),
        "wh_grid_export": float(row.get("wh_grid_export", "0.0") or "0.0"),
        "is_complete": (row.get("is_complete", "true") or "true").strip().lower() == "true",
    }


# --- Given --------------------------------------------------------


@given("the energy windows (Pacific) starting {date} are:")
def step_windows_starting(context: Context, date: str) -> None:
    """Register one Pacific day's fixture windows, keyed like solar_status_steps.py's

    `_register_day_windows` so `environment.py`'s shared windows handler serves
    both single-day and (via its [start, end) sweep) multi-day period queries.
    """
    start_utc, _end_utc = pacific_day_bounds(date)
    base = int(start_utc.timestamp())
    windows = []
    for i, row in enumerate(context.table):
        window = _make_window(row)
        window["window_start"] = base + i * _WINDOW_SECONDS
        windows.append(window)
    context.day_windows_by_start[start_utc.isoformat()] = windows


@given("the bridge's inverter arrays are:")
def step_inverter_arrays(context: Context) -> None:
    arrays_by_name: dict[str, list[dict[str, Any]]] = {}
    for row in context.table:
        is_online = row["is_online"].strip().lower() == "true"
        arrays_by_name.setdefault(row["array"], []).append(
            {
                "serial_number": row["serial"],
                "watts_output": float(row["watts_output"]),
                "is_online": is_online,
                "last_report_date": int(context.fixed_now.timestamp()) if is_online else 0,
            }
        )

    payload = [
        {
            "name": name,
            "total_watts": sum(i["watts_output"] for i in inverters),
            "online_count": sum(1 for i in inverters if i["is_online"]),
            "total_count": len(inverters),
            "inverters": inverters,
        }
        for name, inverters in arrays_by_name.items()
    ]

    context.respx_mock.get(f"{BRIDGE_URL}/api/inverters/arrays").mock(
        return_value=httpx.Response(
            200, json={"window_start": int(context.fixed_now.timestamp()), "arrays": payload}
        )
    )


# --- When --------------------------------------------------------


@when("I compare the period {start_a} to {end_a} against the period {start_b} to {end_b}")
def step_compare_periods(
    context: Context, start_a: str, end_a: str, start_b: str, end_b: str
) -> None:
    context.result = asyncio.run(
        compare_periods_tool(start_a=start_a, end_a=end_a, start_b=start_b, end_b=end_b)
    )


@when("I ask whether any inverters need attention")
def step_ask_inverter_health(context: Context) -> None:
    context.result = asyncio.run(get_inverter_health_tool())


# --- Then: period comparison --------------------------------------------------------


@then("period A's produced energy is {value:f} kWh")
def step_then_period_a_produced(context: Context, value: float) -> None:
    assert isinstance(context.result, PeriodComparison)
    assert context.result.period_a.produced_kwh == value


@then("period B's produced energy is {value:f} kWh")
def step_then_period_b_produced(context: Context, value: float) -> None:
    assert isinstance(context.result, PeriodComparison)
    assert context.result.period_b.produced_kwh == value


@then("the period produced energy difference is {value:f} kWh")
def step_then_period_produced_diff(context: Context, value: float) -> None:
    assert isinstance(context.result, PeriodComparison)
    assert context.result.produced_kwh_diff == value


@then("the period produced energy percent difference is {value:f} percent")
def step_then_period_produced_pct_diff(context: Context, value: float) -> None:
    assert isinstance(context.result, PeriodComparison)
    assert context.result.produced_pct_diff == value


# --- Then: inverter health --------------------------------------------------------


@then("{count:d} inverter needs attention")
@then("{count:d} inverters need attention")
def step_then_attention_count(context: Context, count: int) -> None:
    assert isinstance(context.result, InverterHealth)
    assert len(context.result.attention_needed) == count


@then("the inverter needing attention has serial {serial} in array {array}")
def step_then_attention_detail(context: Context, serial: str, array: str) -> None:
    assert isinstance(context.result, InverterHealth)
    matches = [
        o for o in context.result.attention_needed if o.serial == serial and o.array == array
    ]
    assert matches, f"no offline inverter with serial {serial} in array {array}"
