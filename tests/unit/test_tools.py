"""Unit tests for the MCP tool functions in server.py.

Tool functions are called directly (the `@server.tool()` decorator returns
the undecorated function). All bridge calls are mocked via respx — never
hits the network. Where "today"/"yesterday" matter, the server module's
`datetime.now` is monkeypatched to a fixed instant.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

import httpx
import pytest
import respx
from mcp.server.mcpserver.exceptions import ToolError

from enphase_bridge_mcp import server as server_module
from enphase_bridge_mcp.server import compare_days, get_current_status, get_daily_summary

BRIDGE_URL = "http://localhost:8080"

# Pinned "now": 2026-06-15T18:00:00Z == 2026-06-15T11:00:00-07:00 (Pacific, PDT).
FIXED_NOW = datetime(2026, 6, 15, 18, 0, 0, tzinfo=UTC)


class _FixedDateTime(datetime):
    @classmethod
    def now(cls, tz: Any = None) -> datetime:  # noqa: ANN401
        return FIXED_NOW if tz is not None else FIXED_NOW.replace(tzinfo=None)


@pytest.fixture
def pinned_now(monkeypatch: pytest.MonkeyPatch) -> datetime:
    """Freeze `enphase_bridge_mcp.server`'s notion of "now" to FIXED_NOW."""
    monkeypatch.setattr(server_module, "datetime", _FixedDateTime)
    return FIXED_NOW


def make_window(
    window_start: int,
    wh_produced: float,
    wh_consumed: float,
    wh_grid_import: float = 0.0,
    wh_grid_export: float = 0.0,
    is_complete: bool = True,
) -> dict[str, Any]:
    return {
        "window_start": window_start,
        "wh_produced": wh_produced,
        "wh_consumed": wh_consumed,
        "wh_grid_import": wh_grid_import,
        "wh_grid_export": wh_grid_export,
        "is_complete": is_complete,
    }


def windows_page(payload: list[dict[str, Any]]) -> dict[str, Any]:
    return {"windows": payload, "total": len(payload), "limit": 2880, "offset": 0}


def mock_windows(payload: list[dict[str, Any]]) -> None:
    respx.get(f"{BRIDGE_URL}/api/energy/windows").mock(
        return_value=httpx.Response(200, json=windows_page(payload))
    )


# --- get_daily_summary --------------------------------------------------------


@respx.mock
async def test_get_daily_summary_happy_path_and_math() -> None:
    # 2026-06-14 Pacific midnight == 2026-06-14T07:00:00Z (PDT).
    windows = [
        make_window(1781420400, 500.0, 300.0, 0.0, 200.0, is_complete=True),  # 00:00 Pacific
        make_window(1781421300, 600.0, 300.0, 0.0, 300.0, is_complete=True),  # 00:15 Pacific
        make_window(1781422200, 700.0, 300.0, 0.0, 400.0, is_complete=True),  # 00:30 Pacific
        make_window(1781423100, 800.0, 300.0, 0.0, 500.0, is_complete=False),  # 00:45 Pacific
    ]
    mock_windows(windows)

    result = await get_daily_summary(date="2026-06-14")

    assert result.date == "2026-06-14"
    assert result.produced_kwh == 2.6  # (500+600+700+800) Wh
    assert result.consumed_kwh == 1.2  # 4 * 300 Wh
    assert result.imported_kwh == 0.0
    assert result.exported_kwh == 1.4  # (200+300+400+500) Wh
    assert result.net_kwh == 1.4  # 2.6 - 1.2
    assert result.self_consumption_pct == 46.15  # (2600-1400)/2600*100
    # Peak is chosen only among complete windows: the 800 Wh window is
    # incomplete (trailing, in-progress), so the 700 Wh complete window wins.
    assert result.peak_production_w == 2800.0  # 700 Wh window * 4
    assert result.peak_production_at == "2026-06-14T00:30:00-07:00"
    # 3 complete windows out of 96 expected for a full past day, not out of
    # the 4 the bridge happened to return.
    assert result.data_completeness_pct == 3.12


@respx.mock
async def test_get_daily_summary_no_windows_raises_tool_error() -> None:
    mock_windows([])
    with pytest.raises(ToolError, match="no energy data"):
        await get_daily_summary(date="2026-06-10")


async def test_get_daily_summary_bad_date_raises_tool_error() -> None:
    with pytest.raises(ToolError, match="Invalid date_spec"):
        await get_daily_summary(date="not-a-date")


@respx.mock
async def test_get_daily_summary_today_uses_pinned_clock(pinned_now: datetime) -> None:
    windows = [make_window(1781506800, 100.0, 50.0, is_complete=True)]  # 00:00 Pacific 2026-06-15
    mock_windows(windows)

    result = await get_daily_summary(date="today")

    assert result.date == "2026-06-15"


# --- get_current_status --------------------------------------------------------


@respx.mock
async def test_get_current_status_happy_path(pinned_now: datetime) -> None:
    now_epoch = int(FIXED_NOW.timestamp())
    window_start = now_epoch - 600  # 10 minutes ago -> online

    respx.get(f"{BRIDGE_URL}/api/health").mock(
        return_value=httpx.Response(
            200,
            json={
                "status": "ok",
                "last_window_start": window_start,
                "token_expires_at": 1900000000,
                "uptime_seconds": 12345,
            },
        )
    )
    respx.get(f"{BRIDGE_URL}/api/energy/windows/latest").mock(
        return_value=httpx.Response(200, json=make_window(window_start, 900.0, 400.0, 0.0, 300.0))
    )
    respx.get(f"{BRIDGE_URL}/api/power/samples").mock(
        return_value=httpx.Response(
            200,
            json={
                "samples": [
                    {
                        "sampled_at": now_epoch - 60,
                        "production_w": 1200.0,
                        "consumption_w": 800.0,
                        "grid_w": -400.0,
                    }
                ],
                "total": 1,
                "limit": 50,
                "offset": 0,
            },
        )
    )
    today_windows = [
        make_window(1781506800, 1000.0, 400.0, 0.0, 300.0),
        make_window(1781507700, 1500.0, 600.0, 0.0, 500.0),
    ]
    mock_windows(today_windows)

    result = await get_current_status()

    assert result.production_w == 1200.0
    assert result.consumption_w == 800.0
    assert result.grid_w == -400.0
    # 800 consumed = 1200 produced + (-400) exported: channels agree exactly.
    assert result.power_balance_w == 0.0
    assert result.is_power_data_consistent is True
    assert result.is_online is True
    assert result.last_data_at == "2026-06-15T10:50:00-07:00"
    assert result.today_produced_kwh == 2.5  # (1000+1500) Wh
    assert result.today_consumed_kwh == 1.0  # (400+600) Wh
    assert result.today_exported_kwh == 0.8  # (300+500) Wh
    # 2 complete windows out of 44 expected windows between Pacific midnight
    # and the pinned "now" (11:00 Pacific).
    assert result.today_data_completeness_pct == 4.55
    assert result.uptime_seconds == 12345


@respx.mock
async def test_get_current_status_flags_contradictory_power_channels(
    pinned_now: datetime,
) -> None:
    """Real-world regression: the bridge once reported negative consumption with
    zero grid flow while producing 2850 W — physically impossible together. The
    tool must flag it, not pass it through as trustworthy."""
    now_epoch = int(FIXED_NOW.timestamp())
    window_start = now_epoch - 600

    respx.get(f"{BRIDGE_URL}/api/health").mock(
        return_value=httpx.Response(
            200,
            json={
                "status": "ok",
                "last_window_start": window_start,
                "token_expires_at": 1900000000,
                "uptime_seconds": 12345,
            },
        )
    )
    respx.get(f"{BRIDGE_URL}/api/energy/windows/latest").mock(
        return_value=httpx.Response(200, json=make_window(window_start, 900.0, 400.0, 0.0, 300.0))
    )
    respx.get(f"{BRIDGE_URL}/api/power/samples").mock(
        return_value=httpx.Response(
            200,
            json={
                "samples": [
                    {
                        "sampled_at": now_epoch - 60,
                        "production_w": 2850.0,
                        "consumption_w": -543.0,
                        "grid_w": 0.0,
                    }
                ],
                "total": 1,
                "limit": 50,
                "offset": 0,
            },
        )
    )
    mock_windows([make_window(1781506800, 1000.0, 400.0, 0.0, 300.0)])

    result = await get_current_status()

    assert result.power_balance_w == -3393.0  # -543 - (2850 + 0)
    assert result.is_power_data_consistent is False
    # The raw channels still pass through unaltered — flagged, never rewritten.
    assert result.consumption_w == -543.0


def test_power_consistency_boundaries() -> None:
    """The two independent triggers: balance residual beyond tolerance, and
    negative consumption beyond the noise floor even when balanced."""
    from enphase_bridge_mcp.server import _is_power_consistent, _power_balance_w

    # Residual exactly at tolerance is still consistent; just past it is not.
    assert _is_power_consistent(consumption_w=800.0, power_balance_w=500.0) is True
    assert _is_power_consistent(consumption_w=800.0, power_balance_w=-500.0) is True
    assert _is_power_consistent(consumption_w=800.0, power_balance_w=500.01) is False

    # Negative consumption within balance tolerance must still be flagged:
    # production 400, consumption -50, grid 0 balances to -450 (< 500 W)
    # but a home can't consume -50 W.
    residual = _power_balance_w(production_w=400.0, consumption_w=-50.0, grid_w=0.0)
    assert abs(residual) <= 500.0
    assert _is_power_consistent(consumption_w=-50.0, power_balance_w=residual) is False

    # A few watts below zero is CT noise at idle, not a fault.
    assert _is_power_consistent(consumption_w=-10.0, power_balance_w=0.0) is True


@respx.mock
async def test_get_current_status_is_online_at_worst_case_staleness(pinned_now: datetime) -> None:
    """A healthy bridge's `window_start` age cycles from 900s (just after write) up to
    1800s (just before the next 15-min boundary, when the next window is about to be
    written). `is_online` must stay True across that whole range, since it reflects the
    window's *end* time, not its start.
    """
    now_epoch = int(FIXED_NOW.timestamp())
    window_start = now_epoch - 1799  # worst-case age just before the next boundary

    respx.get(f"{BRIDGE_URL}/api/health").mock(
        return_value=httpx.Response(
            200,
            json={
                "status": "ok",
                "last_window_start": window_start,
                "token_expires_at": 1900000000,
                "uptime_seconds": 1,
            },
        )
    )
    respx.get(f"{BRIDGE_URL}/api/energy/windows/latest").mock(
        return_value=httpx.Response(200, json=make_window(window_start, 900.0, 400.0))
    )
    respx.get(f"{BRIDGE_URL}/api/power/samples").mock(
        return_value=httpx.Response(
            200,
            json={
                "samples": [
                    {
                        "sampled_at": now_epoch - 60,
                        "production_w": 1200.0,
                        "consumption_w": 800.0,
                        "grid_w": -400.0,
                    }
                ],
                "total": 1,
                "limit": 50,
                "offset": 0,
            },
        )
    )
    mock_windows([])

    result = await get_current_status()

    assert result.is_online is True


@respx.mock
async def test_get_current_status_no_power_samples_raises_tool_error(pinned_now: datetime) -> None:
    now_epoch = int(FIXED_NOW.timestamp())
    health_body = {
        "status": "ok",
        "last_window_start": now_epoch,
        "token_expires_at": 0,
        "uptime_seconds": 1,
    }
    respx.get(f"{BRIDGE_URL}/api/health").mock(return_value=httpx.Response(200, json=health_body))
    respx.get(f"{BRIDGE_URL}/api/energy/windows/latest").mock(
        return_value=httpx.Response(200, json=make_window(now_epoch, 1.0, 1.0))
    )
    respx.get(f"{BRIDGE_URL}/api/power/samples").mock(
        return_value=httpx.Response(200, json={"samples": [], "total": 0, "limit": 50, "offset": 0})
    )

    with pytest.raises(ToolError, match="no power samples"):
        await get_current_status()


@respx.mock
async def test_get_current_status_bridge_down_raises_tool_error() -> None:
    respx.get(f"{BRIDGE_URL}/api/health").mock(side_effect=httpx.ConnectError("refused"))

    with pytest.raises(ToolError, match="Cannot reach enphase-bridge"):
        await get_current_status()


# --- compare_days --------------------------------------------------------


@respx.mock
async def test_compare_days_happy_path_with_deltas() -> None:
    day_a_windows = [
        make_window(1, 1000.0, 500.0, 0.0, 300.0),
        make_window(2, 1500.0, 700.0, 0.0, 400.0),
    ]
    day_b_windows = [
        make_window(3, 800.0, 600.0, 0.0, 100.0),
        make_window(4, 1200.0, 600.0, 0.0, 200.0),
    ]
    route = respx.get(f"{BRIDGE_URL}/api/energy/windows")
    route.side_effect = [
        httpx.Response(200, json=windows_page(day_a_windows)),
        httpx.Response(200, json=windows_page(day_b_windows)),
    ]

    result = await compare_days(date_a="2026-06-15", date_b="2026-06-14")

    # day_a: produced=2.5kWh consumed=1.2kWh net=1.3kWh
    # day_b: produced=2.0kWh consumed=1.2kWh net=0.8kWh
    assert result.day_a.produced_kwh == 2.5
    assert result.day_b.produced_kwh == 2.0
    assert result.produced_kwh_diff == 0.5
    assert result.produced_pct_diff == 25.0  # (2.5-2.0)/2.0*100
    assert result.consumed_kwh_diff == 0.0
    assert result.consumed_pct_diff == 0.0
    assert result.net_kwh_diff == 0.5  # 1.3 - 0.8
    assert result.net_pct_diff == 62.5  # (1.3-0.8)/0.8*100


@respx.mock
async def test_compare_days_guards_divide_by_zero() -> None:
    day_a_windows = [make_window(1, 1000.0, 500.0)]  # produced 1.0 kWh
    day_b_windows = [make_window(2, 0.0, 500.0)]  # produced 0.0 kWh

    route = respx.get(f"{BRIDGE_URL}/api/energy/windows")
    route.side_effect = [
        httpx.Response(200, json=windows_page(day_a_windows)),
        httpx.Response(200, json=windows_page(day_b_windows)),
    ]

    result = await compare_days(date_a="2026-06-15", date_b="2026-06-14")

    assert result.produced_kwh_diff == 1.0
    assert result.produced_pct_diff == 0.0  # guarded: day_b's produced_kwh is 0


async def test_compare_days_bad_date_raises_tool_error() -> None:
    with pytest.raises(ToolError, match="Invalid date_spec"):
        await compare_days(date_a="not-a-date", date_b="yesterday")


# --- compare_days: same_time_of_day --------------------------------------------------------


def mock_windows_filtered(all_windows: list[dict[str, Any]]) -> respx.Route:
    """Mock `/api/energy/windows` filtering by the request's start/end query
    params, unlike `mock_windows` (which returns the same payload regardless
    of query). Needed to prove `same_time_of_day` truncation actually changes
    which windows get fetched, not just what `compare_days` does with a fixed
    canned response.
    """

    def responder(request: httpx.Request) -> httpx.Response:
        start = datetime.fromisoformat(request.url.params["start"])
        end = datetime.fromisoformat(request.url.params["end"])
        filtered = [
            w for w in all_windows if start.timestamp() <= w["window_start"] < end.timestamp()
        ]
        return httpx.Response(200, json=windows_page(filtered))

    return respx.get(f"{BRIDGE_URL}/api/energy/windows").mock(side_effect=responder)


@respx.mock
async def test_compare_days_same_time_of_day_truncates_complete_day(pinned_now: datetime) -> None:
    """At the pinned 11:00 Pacific "now", today-vs-yesterday with
    same_time_of_day=True must cut yesterday down to its own 00:00-11:00
    Pacific span to match today's so-far span -- not yesterday's full day.
    """
    y0 = 1781420400  # 2026-06-14T00:00:00-07:00 Pacific ("yesterday")
    yesterday_windows = [
        make_window(y0 + 0 * 3600, 1000.0, 200.0),  # 00:00 Pacific
        make_window(y0 + 5 * 3600, 1000.0, 200.0),  # 05:00 Pacific
        make_window(y0 + 10 * 3600, 1000.0, 200.0),  # 10:00 Pacific
        make_window(y0 + 15 * 3600, 1000.0, 200.0),  # 15:00 Pacific -- after cutoff
        make_window(y0 + 20 * 3600, 1000.0, 200.0),  # 20:00 Pacific -- after cutoff
    ]
    t0 = 1781506800  # 2026-06-15T00:00:00-07:00 Pacific ("today")
    today_windows = [
        make_window(t0 + 0 * 3600, 1000.0, 200.0),  # 00:00 Pacific
        make_window(t0 + 5 * 3600, 1000.0, 200.0),  # 05:00 Pacific
    ]
    mock_windows_filtered(yesterday_windows + today_windows)

    truncated = await compare_days(date_a="today", date_b="yesterday", same_time_of_day=True)
    full = await compare_days(date_a="today", date_b="yesterday", same_time_of_day=False)

    # today is unaffected by the flag either way: 2 windows * 1000 Wh = 2.0 kWh.
    assert truncated.day_a.produced_kwh == 2.0
    assert full.day_a.produced_kwh == 2.0

    # yesterday truncated to 00:00-11:00 Pacific: only the 00:00/05:00/10:00
    # windows fall inside -> 3 * 1000 Wh = 3.0 kWh.
    assert truncated.day_b.produced_kwh == 3.0
    # yesterday untouched: all 5 windows -> 5.0 kWh.
    assert full.day_b.produced_kwh == 5.0

    # Proof the truncation changes the comparison itself, not just cosmetics:
    # the percent deltas differ numerically depending on the flag.
    assert truncated.produced_pct_diff == -33.33  # (2.0-3.0)/3.0*100
    assert full.produced_pct_diff == -60.0  # (2.0-5.0)/5.0*100
    assert truncated.produced_pct_diff != full.produced_pct_diff


@respx.mock
async def test_compare_days_same_time_of_day_noop_when_both_days_complete(
    pinned_now: datetime,
) -> None:
    """same_time_of_day=True must not truncate anything when neither day is
    today -- both days are already complete, so there's no partial day to
    match against, per the tool's documented no-op case."""
    a0 = 1781074800  # 2026-06-10T00:00:00-07:00 Pacific
    b0 = 1780642800  # 2026-06-05T00:00:00-07:00 Pacific
    day_a_windows = [
        make_window(a0, 1000.0, 500.0),
        make_window(a0 + 3600, 1500.0, 700.0),
    ]
    day_b_windows = [
        make_window(b0, 800.0, 600.0),
        make_window(b0 + 3600, 1200.0, 600.0),
    ]
    mock_windows_filtered(day_a_windows + day_b_windows)

    result = await compare_days(date_a="2026-06-10", date_b="2026-06-05", same_time_of_day=True)
    baseline = await compare_days(date_a="2026-06-10", date_b="2026-06-05", same_time_of_day=False)

    assert result == baseline
    assert result.day_a.produced_kwh == 2.5  # (1000+1500) Wh, full day, untruncated
    assert result.day_b.produced_kwh == 2.0  # (800+1200) Wh, full day, untruncated
