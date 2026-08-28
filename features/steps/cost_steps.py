"""Step definitions for features/cost.feature.

Given steps build bridge fixtures (respx-mocked, via features/environment.py).
When steps call the milestone-3 MCP tool coroutines directly with
`asyncio.run`. Mirrors the style of `analysis_steps.py`.
"""

from __future__ import annotations

import asyncio

import httpx
from behave import given, then, when
from behave.runner import Context

from enphase_bridge_mcp.cost_tools import TrueUpEstimate
from enphase_bridge_mcp.cost_tools import get_trueup_estimate as get_trueup_estimate_tool

BRIDGE_URL = "http://localhost:8080"
_PERIODS = ("peak", "off_peak", "super_off_peak")


# --- Given --------------------------------------------------------


@given("the true-up breakdown for {start} to {end} (Pacific) is:")
def step_trueup_breakdown(context: Context, start: str, end: str) -> None:
    """Register a `/api/trueup/estimate` fixture from a per-TOU-period table.

    `net_cost_usd` is derived from the table (total import cost minus total
    export credit) rather than specified separately, so the fixture can't
    drift from the numbers it's built from.
    """
    rows = {row["period"]: row for row in context.table}
    context.trueup_breakdown_table = rows

    def detail(period: str) -> dict[str, float]:
        row = rows[period]
        return {
            "import_kwh": float(row["import_kwh"]),
            "export_kwh": float(row["export_kwh"]),
            "import_cost_usd": float(row["import_cost_usd"]),
            "export_credit_usd": float(row["export_credit_usd"]),
        }

    breakdown = {period: detail(period) for period in _PERIODS}
    net_cost_usd = sum(d["import_cost_usd"] for d in breakdown.values()) - sum(
        d["export_credit_usd"] for d in breakdown.values()
    )

    context.respx_mock.get(f"{BRIDGE_URL}/api/trueup/estimate").mock(
        return_value=httpx.Response(
            200,
            json={
                "period_start": int(context.fixed_now.timestamp()),
                "period_end": int(context.fixed_now.timestamp()),
                "net_cost_usd": round(net_cost_usd, 2),
                "breakdown": breakdown,
                "tou_schedule": {
                    "id": 1,
                    "rate_label": "EV2-A",
                    "effective_date": "2026-01-01",
                },
                "computed_at": int(context.fixed_now.timestamp()),
                "excluded_window_count": 0,
            },
        )
    )


# --- When --------------------------------------------------------


@when("I ask for the true-up estimate from {start} to {end}")
def step_ask_trueup_estimate(context: Context, start: str, end: str) -> None:
    context.result = asyncio.run(get_trueup_estimate_tool(start_date=start, end_date=end))


# --- Then --------------------------------------------------------


@then("the true-up net cost is {value:f} USD")
def step_then_trueup_net_cost(context: Context, value: float) -> None:
    assert isinstance(context.result, TrueUpEstimate)
    assert context.result.net_cost_usd == value


@then("the true-up excluded window count is {value:d}")
def step_then_trueup_excluded(context: Context, value: int) -> None:
    assert isinstance(context.result, TrueUpEstimate)
    assert context.result.excluded_window_count == value


@then("the true-up breakdown matches the table")
def step_then_trueup_breakdown_matches_table(context: Context) -> None:
    """Pins the per-TOU-period breakdown against the same table the Given
    step's fixture was built from, so a dropped/mis-keyed field in
    `_period_breakdown` fails the scenario instead of passing unnoticed."""
    assert isinstance(context.result, TrueUpEstimate)
    rows = context.trueup_breakdown_table
    for period in _PERIODS:
        row = rows[period]
        breakdown = getattr(context.result, period)
        assert breakdown.import_kwh == float(row["import_kwh"]), period
        assert breakdown.export_kwh == float(row["export_kwh"]), period
        assert breakdown.import_cost_usd == float(row["import_cost_usd"]), period
        assert breakdown.export_credit_usd == float(row["export_credit_usd"]), period
