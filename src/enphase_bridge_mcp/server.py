"""MCP server exposing enphase-bridge solar data as three LLM tools.

Stateless streamable-HTTP server (mcp==2.0.0b1): every tool call constructs
its own `Settings`/`BridgeClient`, matching `BridgeClient`'s own
per-call-connection design. No shared mutable state between calls.
"""

from __future__ import annotations

from datetime import UTC, datetime

from mcp.server.mcpserver import MCPServer
from mcp.server.mcpserver.exceptions import ToolError
from pydantic import BaseModel
from starlette.applications import Starlette

from .bridge_client import BridgeClient
from .config import Settings
from .formatting import PACIFIC, epoch_to_pacific_iso, pacific_day_bounds, wh_to_kwh

server: MCPServer = MCPServer(
    name="enphase-bridge-mcp",
    instructions=(
        "Tools for querying a home solar installation via the local "
        "enphase-bridge service. All energy figures are kWh, all power "
        "figures are watts, and all timestamps are America/Los_Angeles "
        "(Pacific) ISO 8601 strings."
    ),
)


class CurrentStatus(BaseModel):
    """Live snapshot of the solar system plus today's running totals."""

    production_w: float
    """Instantaneous solar production, in watts."""
    consumption_w: float
    """Instantaneous site consumption, in watts."""
    grid_w: float
    """Instantaneous grid flow, in watts. Negative means exporting to the grid."""
    is_online: bool
    """True if the bridge has recorded a completed window within the last ~20 minutes."""
    last_data_at: str
    """Pacific ISO 8601 timestamp of the most recent completed energy window."""
    today_produced_kwh: float
    """Energy produced so far today (since Pacific midnight), in kWh."""
    today_consumed_kwh: float
    """Energy consumed so far today (since Pacific midnight), in kWh."""
    today_exported_kwh: float
    """Energy exported to the grid so far today (since Pacific midnight), in kWh."""
    today_data_completeness_pct: float
    """Share of today's expected 15-minute windows (so far) marked complete by the bridge, 0-100.

    A value below 100 means the running totals above are based on partial or
    missing data (collector gap, restart, etc.) rather than a full record of
    the day so far.
    """
    uptime_seconds: int
    """Seconds since the enphase-bridge process started."""


class DailySummary(BaseModel):
    """Aggregated energy totals for one Pacific civil day."""

    date: str
    """The Pacific civil date this summary covers, as YYYY-MM-DD."""
    produced_kwh: float
    consumed_kwh: float
    imported_kwh: float
    exported_kwh: float
    net_kwh: float
    """produced_kwh - consumed_kwh: positive means the site generated a surplus that day."""
    self_consumption_pct: float
    """Share of produced energy consumed on-site rather than exported, 0-100."""
    peak_production_w: float
    """Highest average production across any 15-minute window that day, in watts."""
    peak_production_at: str
    """Pacific ISO 8601 start time of the peak-production window."""
    data_completeness_pct: float
    """Share of that day's 15-minute windows marked complete by the bridge, 0-100."""


class DayComparison(BaseModel):
    """Two daily summaries plus the deltas between them (day_a minus day_b)."""

    day_a: DailySummary
    day_b: DailySummary
    produced_kwh_diff: float
    produced_pct_diff: float
    """Percent change in produced_kwh, day_a vs day_b. 0.0 if day_b's value is zero."""
    consumed_kwh_diff: float
    consumed_pct_diff: float
    """Percent change in consumed_kwh, day_a vs day_b. 0.0 if day_b's value is zero."""
    net_kwh_diff: float
    net_pct_diff: float
    """Percent change in net_kwh, day_a vs day_b. 0.0 if day_b's value is zero."""


def _build_client() -> BridgeClient:
    return BridgeClient(Settings())


def _now() -> datetime:
    """Current instant, resolved through this module's `datetime` global.

    Exists so other modules (e.g. `analysis_tools`) can share one clock that
    tests pin the same way `test_tools.py`'s `pinned_now` fixture already
    does: by monkeypatching `enphase_bridge_mcp.server.datetime`.
    """
    return datetime.now(tz=UTC)


async def _build_daily_summary(client: BridgeClient, date_spec: str, now: datetime) -> DailySummary:
    """Fetch and aggregate one Pacific day's windows into a `DailySummary`.

    Raises:
        ValueError: `date_spec` is not "today", "yesterday", or "YYYY-MM-DD".
        ToolError: the bridge has no windows recorded for that day.
    """
    start_utc, end_utc = pacific_day_bounds(date_spec, now=now)
    windows = await client.list_windows(start_utc, end_utc)
    if not windows:
        raise ToolError(f"enphase-bridge has no energy data for {date_spec} (Pacific)")

    produced_wh = sum(w["wh_produced"] for w in windows)
    consumed_wh = sum(w["wh_consumed"] for w in windows)
    imported_wh = sum(w["wh_grid_import"] for w in windows)
    exported_wh = sum(w["wh_grid_export"] for w in windows)

    produced_kwh = wh_to_kwh(produced_wh)
    consumed_kwh = wh_to_kwh(consumed_wh)
    imported_kwh = wh_to_kwh(imported_wh)
    exported_kwh = wh_to_kwh(exported_wh)
    net_kwh = round(produced_kwh - consumed_kwh, 2)

    self_consumption_pct = (
        round(max(0.0, min(100.0, (produced_wh - exported_wh) / produced_wh * 100)), 2)
        if produced_wh > 0
        else 0.0
    )

    # A trailing in-progress window's Wh understates a full 15 minutes, so an
    # incomplete window should never be picked as the peak-power window.
    peak_candidates = [w for w in windows if w["is_complete"]] or windows
    peak_window = max(peak_candidates, key=lambda w: w["wh_produced"])
    peak_production_w = round(peak_window["wh_produced"] * 4, 1)
    peak_production_at = epoch_to_pacific_iso(int(peak_window["window_start"]))

    # Denominator is the number of 15-minute windows expected to exist by now
    # (not len(windows)) — otherwise missing rows are invisible: a day with
    # only 4 windows recorded due to a collector outage would report 100%
    # complete just because all 4 happen to be marked complete.
    expected_windows = max(1, int((min(now, end_utc) - start_utc).total_seconds() // 900))
    complete_count = sum(1 for w in windows if w["is_complete"])
    data_completeness_pct = round(complete_count / expected_windows * 100, 2)

    resolved_date = start_utc.astimezone(PACIFIC).date().isoformat()

    return DailySummary(
        date=resolved_date,
        produced_kwh=produced_kwh,
        consumed_kwh=consumed_kwh,
        imported_kwh=imported_kwh,
        exported_kwh=exported_kwh,
        net_kwh=net_kwh,
        self_consumption_pct=self_consumption_pct,
        peak_production_w=peak_production_w,
        peak_production_at=peak_production_at,
        data_completeness_pct=data_completeness_pct,
    )


def _pct_diff(a: float, b: float) -> float:
    """Percent change of `a` relative to `b`. 0.0 when `b` is zero (documented edge case)."""
    if b == 0:
        return 0.0
    return round((a - b) / abs(b) * 100, 2)


@server.tool()
async def get_current_status() -> CurrentStatus:
    """Get the solar system's live status: current power flow and today's running totals.

    Returns instantaneous production/consumption/grid power in watts (grid_w is
    negative while exporting), whether the bridge is currently online, when it
    last recorded data (Pacific ISO 8601), today's produced/consumed/exported
    energy in kWh accumulated since Pacific midnight, and what share of today's
    expected 15-minute windows so far the bridge has marked complete. Raises
    an error if the bridge is unreachable or has no recent power samples.
    """
    client = _build_client()
    now = _now()

    health = await client.get_health()
    latest_window = await client.get_latest_window()
    window_start = int(latest_window["window_start"])
    # `/api/energy/windows/latest` returns the most recently *completed* window,
    # stamped with its start time — so staleness must be measured from the
    # window's end (start + 900s), not its start, or a healthy bridge looks
    # offline for most of each 15-minute cycle.
    window_end = window_start + 900
    is_online = (now.timestamp() - window_end) <= 20 * 60
    last_data_at = epoch_to_pacific_iso(window_start)

    now_epoch = int(now.timestamp())
    samples = await client.get_power_samples(now_epoch - 300, now_epoch, limit=50)
    if not samples:
        raise ToolError("enphase-bridge returned no power samples in the last 5 minutes")
    latest_sample = max(samples, key=lambda s: s["sampled_at"])

    day_start_utc, _day_end_utc = pacific_day_bounds("today", now=now)
    today_windows = await client.list_windows(day_start_utc, now)
    today_produced_kwh = wh_to_kwh(sum(w["wh_produced"] for w in today_windows))
    today_consumed_kwh = wh_to_kwh(sum(w["wh_consumed"] for w in today_windows))
    today_exported_kwh = wh_to_kwh(sum(w["wh_grid_export"] for w in today_windows))
    expected_today_windows = max(1, int((now - day_start_utc).total_seconds() // 900))
    complete_today_count = sum(1 for w in today_windows if w["is_complete"])
    today_data_completeness_pct = round(complete_today_count / expected_today_windows * 100, 2)

    return CurrentStatus(
        production_w=float(latest_sample["production_w"]),
        consumption_w=float(latest_sample["consumption_w"]),
        grid_w=float(latest_sample["grid_w"]),
        is_online=is_online,
        last_data_at=last_data_at,
        today_produced_kwh=today_produced_kwh,
        today_consumed_kwh=today_consumed_kwh,
        today_exported_kwh=today_exported_kwh,
        today_data_completeness_pct=today_data_completeness_pct,
        uptime_seconds=int(health["uptime_seconds"]),
    )


@server.tool()
async def get_daily_summary(date: str = "today") -> DailySummary:
    """Get aggregated energy totals for one Pacific civil day (midnight to midnight Pacific).

    `date` accepts "today", "yesterday", or an explicit "YYYY-MM-DD" (interpreted
    as a Pacific date). Returns produced/consumed/imported/exported/net kWh,
    self-consumption percentage, peak production (watts, with its Pacific time),
    and what share of that day's 15-minute windows the bridge marked complete.
    Raises an error for an invalid date, or if the bridge has no data for that day.
    """
    client = _build_client()
    try:
        return await _build_daily_summary(client, date, _now())
    except ValueError as exc:
        raise ToolError(str(exc)) from exc


@server.tool()
async def compare_days(date_a: str = "today", date_b: str = "yesterday") -> DayComparison:
    """Compare energy totals between two Pacific civil days.

    Each of `date_a`/`date_b` accepts "today", "yesterday", or "YYYY-MM-DD"
    (Pacific dates). Returns the full `DailySummary` for both days, plus
    kWh and percent deltas (day_a minus/relative-to day_b) for produced,
    consumed, and net energy. Percent deltas are 0.0 when day_b's value is
    zero. Raises an error for an invalid date, or if either day has no data.
    """
    client = _build_client()
    now = _now()
    try:
        day_a = await _build_daily_summary(client, date_a, now)
        day_b = await _build_daily_summary(client, date_b, now)
    except ValueError as exc:
        raise ToolError(str(exc)) from exc

    return DayComparison(
        day_a=day_a,
        day_b=day_b,
        produced_kwh_diff=round(day_a.produced_kwh - day_b.produced_kwh, 2),
        produced_pct_diff=_pct_diff(day_a.produced_kwh, day_b.produced_kwh),
        consumed_kwh_diff=round(day_a.consumed_kwh - day_b.consumed_kwh, 2),
        consumed_pct_diff=_pct_diff(day_a.consumed_kwh, day_b.consumed_kwh),
        net_kwh_diff=round(day_a.net_kwh - day_b.net_kwh, 2),
        net_pct_diff=_pct_diff(day_a.net_kwh, day_b.net_kwh),
    )


# Import-time side effect: registers @server.tool()s defined in analysis_tools.
from . import analysis_tools as _analysis_tools  # noqa: E402,F401

app: Starlette = server.streamable_http_app(stateless_http=True)


def main() -> None:
    settings = Settings()
    server.run(
        transport="streamable-http", stateless_http=True, host=settings.host, port=settings.port
    )


if __name__ == "__main__":
    main()
