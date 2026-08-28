"""Unit tests for the milestone-2 MCP tool functions in analysis_tools.py.

Tool functions are called directly (the `@server.tool()` decorator returns
the undecorated function). All bridge calls are mocked via respx — never
hits the network. `enphase_bridge_mcp.server`'s `datetime` is monkeypatched
to a fixed instant where "now" matters (`analysis_tools._now()` resolves
through that same module global — see `server._now`'s docstring).
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

import httpx
import pytest
import respx
from mcp.server.mcpserver.exceptions import ToolError

from enphase_bridge_mcp import server as server_module
from enphase_bridge_mcp.analysis_tools import (
    compare_periods,
    get_inverter_health,
    get_period_summary,
)
from enphase_bridge_mcp.formatting import epoch_to_pacific_iso, pacific_day_bounds

BRIDGE_URL = "http://localhost:8080"

# Pinned "now": 2026-08-20T18:00:00Z == 2026-08-20T11:00:00-07:00 (Pacific, PDT).
# Chosen well after all fixture date ranges below so every fixture day is
# treated as fully in the past (96/96 expected windows) unless a test says
# otherwise.
FIXED_NOW = datetime(2026, 8, 20, 18, 0, 0, tzinfo=UTC)


class _FixedDateTime(datetime):
    @classmethod
    def now(cls, tz: Any = None) -> datetime:  # noqa: ANN401
        return FIXED_NOW if tz is not None else FIXED_NOW.replace(tzinfo=None)


@pytest.fixture
def pinned_now(monkeypatch: pytest.MonkeyPatch) -> datetime:
    """Freeze `enphase_bridge_mcp.server`'s notion of "now" to FIXED_NOW.

    `analysis_tools._now` is imported from `server`, so patching the clock
    there pins both modules at once.
    """
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


def make_arrays_response(
    arrays: list[dict[str, Any]], window_start: int = 1745712000
) -> dict[str, Any]:
    return {"window_start": window_start, "arrays": arrays}


def mock_arrays(arrays: list[dict[str, Any]], window_start: int = 1745712000) -> None:
    respx.get(f"{BRIDGE_URL}/api/inverters/arrays").mock(
        return_value=httpx.Response(200, json=make_arrays_response(arrays, window_start))
    )


# --- get_period_summary --------------------------------------------------------


@respx.mock
async def test_get_period_summary_happy_path_and_math(pinned_now: datetime) -> None:
    # 2026-06-14 Pacific midnight == 2026-06-14T07:00:00Z (PDT); 2026-06-15
    # Pacific midnight == 2026-06-15T07:00:00Z.
    day1_start = 1781420400  # 2026-06-14 00:00 Pacific
    day2_start = 1781506800  # 2026-06-15 00:00 Pacific
    windows = [
        make_window(day1_start, 500.0, 300.0, 0.0, 200.0),
        make_window(day1_start + 900, 600.0, 300.0, 0.0, 300.0),
        make_window(day2_start, 1000.0, 400.0, 0.0, 300.0),
        make_window(day2_start + 900, 1500.0, 600.0, 0.0, 500.0),
    ]
    mock_windows(windows)

    result = await get_period_summary(start_date="2026-06-14", end_date="2026-06-15")

    assert result.start_date == "2026-06-14"
    assert result.end_date == "2026-06-15"
    assert result.day_count == 2
    assert result.produced_kwh == 3.6  # (500+600+1000+1500) Wh
    assert result.consumed_kwh == 1.6  # (300+300+400+600) Wh
    assert result.exported_kwh == 1.3  # (200+300+300+500) Wh
    assert result.net_kwh == 2.0  # 3.6 - 1.6
    assert result.self_consumption_pct == 63.89  # (3600-1300)/3600*100
    assert result.avg_daily_produced_kwh == 1.8  # 3.6 / 2

    assert len(result.daily_breakdown) == 2
    day1, day2 = result.daily_breakdown
    assert day1.date == "2026-06-14"
    assert day1.produced_kwh == 1.1  # (500+600) Wh
    assert day2.date == "2026-06-15"
    assert day2.produced_kwh == 2.5  # (1000+1500) Wh

    assert result.best_day.date == "2026-06-15"
    assert result.best_day.produced_kwh == 2.5
    assert result.worst_day.date == "2026-06-14"
    assert result.worst_day.produced_kwh == 1.1

    # 4 complete windows out of 96*2 expected for two full past days.
    assert result.data_completeness_pct == round(4 / 192 * 100, 2)

    # Both days have data and are finished, so both count in the average and
    # daily_breakdown must sum back to the period total.
    assert all(d.has_data and not d.is_partial for d in result.daily_breakdown)
    assert round(sum(d.produced_kwh for d in result.daily_breakdown), 2) == result.produced_kwh


@respx.mock
async def test_get_period_summary_single_day_range(pinned_now: datetime) -> None:
    windows = [make_window(1781420400, 500.0, 300.0, 0.0, 200.0, is_complete=True)]
    mock_windows(windows)

    result = await get_period_summary(start_date="2026-06-14", end_date="2026-06-14")

    assert result.day_count == 1
    assert result.produced_kwh == 0.5
    assert result.best_day.date == result.worst_day.date == "2026-06-14"


@respx.mock
async def test_get_period_summary_missing_day_reports_zeros(pinned_now: datetime) -> None:
    """A day with no windows recorded still appears in daily_breakdown, at 0.0 — not omitted —
    but is flagged `has_data=False` and excluded from best/worst/avg so the gap isn't mistaken
    for a genuine zero-production day."""
    day1_start = 1781420400  # 2026-06-14
    windows = [make_window(day1_start, 500.0, 300.0)]
    mock_windows(windows)

    result = await get_period_summary(start_date="2026-06-14", end_date="2026-06-15")

    assert len(result.daily_breakdown) == 2
    present_day, missing_day = result.daily_breakdown
    assert present_day.has_data is True
    assert present_day.is_partial is False
    assert missing_day.date == "2026-06-15"
    assert missing_day.produced_kwh == 0.0
    assert missing_day.consumed_kwh == 0.0
    assert missing_day.net_kwh == 0.0
    assert missing_day.has_data is False
    assert missing_day.is_partial is False

    # The data-less day must never win worst_day just because it zero-fills.
    assert result.worst_day.date == "2026-06-14"
    assert result.best_day.date == "2026-06-14"
    # avg is over the one day that actually has data, not the raw 2-day span.
    assert result.avg_daily_produced_kwh == 0.5


@respx.mock
async def test_get_period_summary_all_days_missing_data_raises_tool_error(
    pinned_now: datetime,
) -> None:
    """The bridge returned windows somewhere (so the top-level empty-result guard doesn't
    fire), but none of them land inside this range's calendar days — there is no finished
    day with data to call best/worst, so this must raise rather than fabricate a winner."""
    windows = [make_window(1, 500.0, 300.0)]  # 1969-12-31 Pacific: outside any 2026 range
    mock_windows(windows)

    with pytest.raises(ToolError, match="no completed day with data"):
        await get_period_summary(start_date="2026-06-14", end_date="2026-06-15")


@respx.mock
async def test_get_period_summary_no_data_raises_tool_error(pinned_now: datetime) -> None:
    mock_windows([])
    with pytest.raises(ToolError, match="no energy data"):
        await get_period_summary(start_date="2026-06-01", end_date="2026-06-05")


async def test_get_period_summary_bad_start_date_raises_tool_error() -> None:
    with pytest.raises(ToolError, match="Invalid start_date"):
        await get_period_summary(start_date="not-a-date", end_date="2026-06-05")


async def test_get_period_summary_bad_end_date_raises_tool_error() -> None:
    with pytest.raises(ToolError, match="Invalid end_date"):
        await get_period_summary(start_date="2026-06-01", end_date="not-a-date")


async def test_get_period_summary_reversed_dates_raises_tool_error() -> None:
    with pytest.raises(ToolError, match="is before start_date"):
        await get_period_summary(start_date="2026-06-05", end_date="2026-06-01")


async def test_get_period_summary_92_days_is_ok(pinned_now: datetime) -> None:
    # 92-day range: 2026-01-01 through 2026-04-02 inclusive == 92 days.
    with respx.mock:
        mock_windows([make_window(1767254400, 100.0, 50.0)])  # 2026-01-01 00:00 Pacific
        result = await get_period_summary(start_date="2026-01-01", end_date="2026-04-02")
    assert result.day_count == 92


async def test_get_period_summary_93_days_raises_tool_error() -> None:
    with pytest.raises(ToolError, match="range too large; max 92 days"):
        await get_period_summary(start_date="2026-01-01", end_date="2026-04-03")


@respx.mock
async def test_get_period_summary_dst_spring_forward_day_has_92_expected_windows(
    pinned_now: datetime,
) -> None:
    """2026-03-08 (Pacific) is the DST spring-forward day: a 23-hour civil day, so only
    92 (not 96) 15-minute windows are expected that day. Exercises the per-day
    `pacific_day_bounds` call inside the expected-window accumulation, not just the
    single-day helpers in test_formatting.py."""
    day_before = 1772870400  # 2026-03-07 00:00 Pacific (PST, 24h day)
    dst_day = 1772956800  # 2026-03-08 00:00 Pacific (spring-forward, 23h day)
    day_after = 1773039600  # 2026-03-09 00:00 Pacific (PDT, 24h day)
    windows = [
        make_window(day_before, 100.0, 50.0),
        make_window(dst_day, 100.0, 50.0),
        make_window(day_after, 100.0, 50.0),
    ]
    mock_windows(windows)

    result = await get_period_summary(start_date="2026-03-07", end_date="2026-03-09")

    # 1 complete window per day out of 96 + 92 + 96 = 284 expected across the three days.
    assert result.data_completeness_pct == round(3 / 284 * 100, 2)


@respx.mock
async def test_get_period_summary_bridge_down_raises_tool_error() -> None:
    respx.get(f"{BRIDGE_URL}/api/energy/windows").mock(side_effect=httpx.ConnectError("refused"))
    with pytest.raises(ToolError, match="Cannot reach enphase-bridge"):
        await get_period_summary(start_date="2026-06-01", end_date="2026-06-02")


@respx.mock
async def test_get_period_summary_avg_excludes_in_progress_today(pinned_now: datetime) -> None:
    """`avg_daily_produced_kwh` must average only finished days that have data — a
    still-in-progress "today" inside the range must not drag it toward its partial
    (so-far) production, even though that partial production still counts toward the
    period's own `produced_kwh` total."""
    day1_start_utc, _ = pacific_day_bounds("2026-08-19", now=pinned_now)
    day2_start_utc, _ = pacific_day_bounds("2026-08-20", now=pinned_now)  # "today"
    windows = [
        make_window(int(day1_start_utc.timestamp()), 4000.0, 2000.0),  # finished: 4.0 kWh
        make_window(int(day2_start_utc.timestamp()), 100.0, 50.0),  # today, partial: 0.1 kWh
    ]
    mock_windows(windows)

    result = await get_period_summary(start_date="2026-08-19", end_date="2026-08-20")

    # The period total DOES include today's partial production.
    assert result.produced_kwh == 4.1
    # But the average must be over the one finished day only (4.0), not
    # (4.0 + 0.1) / 2 = 2.05.
    assert result.avg_daily_produced_kwh == 4.0


@respx.mock
async def test_get_period_summary_daily_breakdown_sum_within_rounding_tolerance(
    pinned_now: datetime,
) -> None:
    """Per-day kWh figures are rounded for display; their sum need not exactly equal
    the period total (independent per-day roundings can differ from the period's
    single rounding by a cent or two), but the drift must stay within ordinary
    display-rounding tolerance, not compound into something larger."""
    days = ["2026-06-01", "2026-06-02", "2026-06-03", "2026-06-04", "2026-06-05"]
    windows = []
    for i, day in enumerate(days):
        start_utc, _ = pacific_day_bounds(day, now=pinned_now)
        # Odd Wh values that don't round cleanly to 2-decimal kWh.
        windows.append(make_window(int(start_utc.timestamp()), 333.33 + i, 111.11 + i))
    mock_windows(windows)

    result = await get_period_summary(start_date="2026-06-01", end_date="2026-06-05")

    breakdown_total = round(sum(d.produced_kwh for d in result.daily_breakdown), 1)
    assert abs(breakdown_total - result.produced_kwh) <= 0.05 * len(days)


# --- compare_periods --------------------------------------------------------


# Real Pacific-midnight epochs (no DST transitions across any of these spans, so days
# increment by exactly 86400s) — unlike epoch 1-4 (1969-12-31 Pacific), these actually
# fall inside the 2026 ranges the tests below request, so they exercise the real
# per-day grouping/best-worst/DST-aware accumulation instead of landing in no day at all.
_JUN08 = 1780902000  # 2026-06-08 00:00 Pacific
_JUN09 = 1780988400  # 2026-06-09 00:00 Pacific
_JUN01 = 1780297200  # 2026-06-01 00:00 Pacific
_JUN02 = 1780383600  # 2026-06-02 00:00 Pacific
_MAY01 = 1777618800  # 2026-05-01 00:00 Pacific


@respx.mock
async def test_compare_periods_happy_path_with_deltas(pinned_now: datetime) -> None:
    period_a_windows = [
        make_window(_JUN08, 1000.0, 500.0, 0.0, 300.0),
        make_window(_JUN09, 1500.0, 700.0, 0.0, 400.0),
    ]
    period_b_windows = [
        make_window(_JUN01, 800.0, 600.0, 0.0, 100.0),
        make_window(_JUN02, 1200.0, 600.0, 0.0, 200.0),
    ]
    route = respx.get(f"{BRIDGE_URL}/api/energy/windows")
    route.side_effect = [
        httpx.Response(200, json=windows_page(period_a_windows)),
        httpx.Response(200, json=windows_page(period_b_windows)),
    ]

    result = await compare_periods(
        start_a="2026-06-08", end_a="2026-06-14", start_b="2026-06-01", end_b="2026-06-07"
    )

    # period_a: produced=2.5kWh consumed=1.2kWh net=1.3kWh
    # period_b: produced=2.0kWh consumed=1.2kWh net=0.8kWh
    assert result.period_a.produced_kwh == 2.5
    assert result.period_b.produced_kwh == 2.0
    assert result.produced_kwh_diff == 0.5
    assert result.produced_pct_diff == 25.0  # (2.5-2.0)/2.0*100
    assert result.consumed_kwh_diff == 0.0
    assert result.consumed_pct_diff == 0.0
    assert result.net_kwh_diff == 0.5  # 1.3 - 0.8
    assert result.net_pct_diff == 62.5  # (1.3-0.8)/0.8*100
    # Both ranges are 7 days here, but each carries its own day_count.
    assert result.period_a.day_count == 7
    assert result.period_b.day_count == 7

    # daily_breakdown must sum back to the period totals for both periods.
    assert (
        round(sum(d.produced_kwh for d in result.period_a.daily_breakdown), 2)
        == result.period_a.produced_kwh
    )
    assert (
        round(sum(d.produced_kwh for d in result.period_b.daily_breakdown), 2)
        == result.period_b.produced_kwh
    )

    # Only the two days with data (of each 7-day range) are eligible for best/worst.
    assert result.period_a.best_day.date == "2026-06-09"
    assert result.period_a.worst_day.date == "2026-06-08"
    assert result.period_b.best_day.date == "2026-06-02"
    assert result.period_b.worst_day.date == "2026-06-01"


@respx.mock
async def test_compare_periods_different_length_ranges_both_reported(pinned_now: datetime) -> None:
    route = respx.get(f"{BRIDGE_URL}/api/energy/windows")
    route.side_effect = [
        httpx.Response(200, json=windows_page([make_window(_JUN01, 100.0, 50.0)])),
        httpx.Response(200, json=windows_page([make_window(_MAY01, 100.0, 50.0)])),
    ]

    result = await compare_periods(
        start_a="2026-06-01", end_a="2026-06-10", start_b="2026-05-01", end_b="2026-05-03"
    )

    assert result.period_a.day_count == 10
    assert result.period_b.day_count == 3


@respx.mock
async def test_compare_periods_guards_divide_by_zero(pinned_now: datetime) -> None:
    period_a_windows = [make_window(_JUN08, 1000.0, 500.0)]  # produced 1.0 kWh
    period_b_windows = [make_window(_JUN01, 0.0, 500.0)]  # produced 0.0 kWh

    route = respx.get(f"{BRIDGE_URL}/api/energy/windows")
    route.side_effect = [
        httpx.Response(200, json=windows_page(period_a_windows)),
        httpx.Response(200, json=windows_page(period_b_windows)),
    ]

    result = await compare_periods(
        start_a="2026-06-08", end_a="2026-06-08", start_b="2026-06-01", end_b="2026-06-01"
    )

    assert result.produced_kwh_diff == 1.0
    assert result.produced_pct_diff == 0.0  # guarded: period_b's produced_kwh is 0


async def test_compare_periods_bad_date_in_period_a_names_period_a() -> None:
    with pytest.raises(ToolError, match="period A: Invalid start_date"):
        await compare_periods(
            start_a="not-a-date", end_a="2026-06-08", start_b="2026-06-01", end_b="2026-06-07"
        )


async def test_compare_periods_bad_date_in_period_b_names_period_b() -> None:
    with pytest.raises(ToolError, match="period B: Invalid end_date"):
        await compare_periods(
            start_a="2026-06-01", end_a="2026-06-07", start_b="2026-06-01", end_b="not-a-date"
        )


async def test_compare_periods_range_too_large_raises_tool_error() -> None:
    with pytest.raises(ToolError, match="period A: range too large; max 92 days"):
        await compare_periods(
            start_a="2026-01-01", end_a="2026-04-03", start_b="2026-06-01", end_b="2026-06-07"
        )


# --- get_inverter_health --------------------------------------------------------


def _two_array_fixture() -> list[dict[str, Any]]:
    return [
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
    ]


@respx.mock
async def test_get_inverter_health_happy_path_all_arrays() -> None:
    mock_arrays(_two_array_fixture())

    result = await get_inverter_health()

    assert [a.name for a in result.arrays] == ["east", "west"]
    assert result.arrays[0].total_watts == 850.0
    assert result.arrays[0].online_count == 2
    assert result.arrays[0].total_count == 2
    assert result.arrays[1].online_count == 0


@respx.mock
async def test_get_inverter_health_reports_freshness(pinned_now: datetime) -> None:
    # Snapshot window starts 5 minutes before "now": window ends 10 minutes ago, well
    # inside the ~20-minute staleness threshold.
    fresh_window_start = int(pinned_now.timestamp()) - 5 * 60
    mock_arrays(_two_array_fixture(), window_start=fresh_window_start)

    result = await get_inverter_health()

    assert result.data_as_of == epoch_to_pacific_iso(fresh_window_start)
    assert result.is_stale is False


@respx.mock
async def test_get_inverter_health_stale_window_flagged(pinned_now: datetime) -> None:
    # Snapshot window started an hour before "now": window ended ~45 minutes ago,
    # well past the ~20-minute staleness threshold.
    stale_window_start = int(pinned_now.timestamp()) - 60 * 60
    mock_arrays(_two_array_fixture(), window_start=stale_window_start)

    result = await get_inverter_health()

    assert result.is_stale is True


@respx.mock
async def test_get_inverter_health_offline_inverters_populate_attention_needed() -> None:
    mock_arrays(_two_array_fixture())

    result = await get_inverter_health()

    assert len(result.attention_needed) == 1
    offline = result.attention_needed[0]
    assert offline.serial == "121847012347"
    assert offline.array == "west"
    assert offline.watts_output == 0.0
    # last_report_date 0 is the bridge's sentinel for "never reported" — must not be
    # surfaced as a 1970 timestamp.
    assert offline.last_report_at is None


@respx.mock
async def test_get_inverter_health_offline_inverter_with_prior_report_gets_timestamp() -> None:
    arrays = _two_array_fixture()
    arrays[1]["inverters"][0]["last_report_date"] = 1745712000  # went offline, but reported once

    mock_arrays(arrays)

    result = await get_inverter_health()

    offline = result.attention_needed[0]
    assert offline.last_report_at == epoch_to_pacific_iso(1745712000)


@respx.mock
async def test_get_inverter_health_no_offline_inverters_gives_empty_attention_needed() -> None:
    arrays = _two_array_fixture()
    arrays[1]["inverters"][0]["is_online"] = True  # make everything healthy
    mock_arrays(arrays)

    result = await get_inverter_health()

    assert result.attention_needed == []


@respx.mock
async def test_get_inverter_health_filters_to_named_array() -> None:
    mock_arrays(_two_array_fixture())

    result = await get_inverter_health(array_name="east")

    assert [a.name for a in result.arrays] == ["east"]
    assert result.attention_needed == []  # east's inverters are all online


@respx.mock
async def test_get_inverter_health_unknown_array_name_lists_valid_names() -> None:
    mock_arrays(_two_array_fixture())

    with pytest.raises(ToolError, match="east, west"):
        await get_inverter_health(array_name="nonexistent")


@respx.mock
async def test_get_inverter_health_no_arrays_recorded_raises_tool_error() -> None:
    mock_arrays([], window_start=1745712000)
    respx.get(f"{BRIDGE_URL}/api/inverters/arrays").mock(
        return_value=httpx.Response(200, json={"window_start": None, "arrays": []})
    )

    with pytest.raises(ToolError, match="no inverter array data"):
        await get_inverter_health()


@respx.mock
async def test_get_inverter_health_bridge_down_raises_tool_error() -> None:
    respx.get(f"{BRIDGE_URL}/api/inverters/arrays").mock(side_effect=httpx.ConnectError("refused"))
    with pytest.raises(ToolError, match="Cannot reach enphase-bridge"):
        await get_inverter_health()
